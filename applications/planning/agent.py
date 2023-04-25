import logging
import math
from applications.planning.utils import setup_results_directory
from tasks import *
from dmas.agents import *
from dmas.network import NetworkConfig

from messages import *
from states import *
from planners import *

class SimulationAgent(Agent):
    def __init__(   self, 
                    results_path : str, 
                    network_name : str,
                    manager_port : int,
                    id : int,
                    manager_network_config: NetworkConfig, 
                    planner_type: PlannerTypes,
                    instruments: list,
                    initial_state: SimulationAgentState, 
                    level: int = logging.INFO, 
                    logger: logging.Logger = None) -> None:
        
        # generate network config 
        agent_network_config = NetworkConfig( 	network_name,
												manager_address_map = {
														zmq.REQ: [f'tcp://localhost:{manager_port}'],
														zmq.SUB: [f'tcp://localhost:{manager_port+1}'],
														zmq.PUSH: [f'tcp://localhost:{manager_port+2}']},
												external_address_map = {
														zmq.REQ: [],
														zmq.PUB: [f'tcp://*:{manager_port+5 + 4*id}'],
														zmq.SUB: [f'tcp://localhost:{manager_port+4}']},
                                                internal_address_map = {
														zmq.REP: [f'tcp://*:{manager_port+5 + 4*id + 1}'],
														zmq.PUB: [f'tcp://*:{manager_port+5 + 4*id + 2}'],
														zmq.SUB: [f'tcp://localhost:{manager_port+5 + 4*id + 3}']
											})
        
        if planner_type is PlannerTypes.ACCBBA:
            planning_module = ACCBBAPlannerModule(  results_path,
                                                    manager_port,
                                                    id,
                                                    agent_network_config,
                                                    level,
                                                    logger)
        elif planner_type is PlannerTypes.FIXED:
            planning_module = FixedPlannerModule(results_path,
                                                 manager_port,
                                                 id,
                                                 agent_network_config,
                                                 level,
                                                 logger)
        else:
            raise NotImplementedError(f'planner of type {planner_type} not yet supported.')
        
        super().__init__(f'AGENT_{id}', 
                        agent_network_config, 
                        manager_network_config, 
                        initial_state, 
                        [planning_module], 
                        level=level, 
                        logger=logger)

        if not isinstance(instruments, list):
            raise AttributeError(f'`instruments` must be of type `list`; is of type {type(instruments)}')

        self.id = id
        self.instruments : list = instruments.copy()
        
        # setup results folder:
        self.results_path = setup_results_directory(results_path+'/'+self.get_element_name())

    async def setup(self) -> None:
        # nothing to set up
        return
    
    async def teardown(self) -> None:
        # log agent capabilities
        out = f'\ninstruments: {self.instruments}'

        # log state 
        out += '\nt, pos, vel, status\n'
        for state_dict in self.state.history:
            out += f"{state_dict['t']}, {state_dict['pos']}, {state_dict['vel']}, {state_dict['status']}\n"    

        self.log(out, level=logging.WARNING)

        # print agent states
        with open(f"{self.results_path}/states.csv", "w") as file:
            title = 't,x_pos,y_pos,x_vel,y_vel,status'
            file.write(title)

            for state_dict in self.state.history:
                pos = state_dict['pos']
                vel = state_dict['vel']
                file.write(f"\n{state_dict['t']},{pos[0]},{pos[1]},{vel[0]},{vel[1]},{state_dict['status']}")

    async def sim_wait(self, delay: float) -> None:
        try:  
            if (
                isinstance(self._clock_config, FixedTimesStepClockConfig) 
                or isinstance(self._clock_config, EventDrivenClockConfig)
                ):
                if delay < 1e-6: 
                    ignored = None
                    return

                # desired time not yet reached
                t0 = self.get_current_time()
                tf = t0 + delay

                # check if failure or critical state will be reached first
                t_failure = self.state.predict_failure() 
                t_crit = self.state.predict_critical()
                if t_failure < tf:
                    tf = t_failure
                elif t_crit < tf:
                    tf = t_crit
                
                # wait for time update        
                ignored = []   
                while self.get_current_time() <= t0:
                    # send tic request
                    tic_req = TicRequest(self.get_element_name(), t0, tf)
                    _, _, content = await self.send_manager_message(tic_req)

                    if content['msg_type'] != ManagerMessageTypes.RECEPTION_ACK.value:
                        raise asyncio.CancelledError()

                    self.log(f'tic request for {tf}[s] sent! waiting on toc broadcast...')
                    dst, src, content = await self.manager_inbox.get()
                    
                    if content['msg_type'] == ManagerMessageTypes.TOC.value:
                        # update clock
                        msg = TocMessage(**content)
                        await self.update_current_time(msg.t)
                        self.log(f'toc received! time updated to: {self.get_current_time()}[s]')
                    else:
                        # ignore message
                        self.log(f'some other manager message was received. ignoring...')
                        ignored.append((dst, src, content))

            elif isinstance(self._clock_config, AcceleratedRealTimeClockConfig):
                await asyncio.sleep(delay / self._clock_config.sim_clock_freq)

            else:
                raise NotImplementedError(f'`sim_wait()` for clock of type {type(self._clock_config)} not yet supported.')
        
        finally:
            if (
                isinstance(self._clock_config, FixedTimesStepClockConfig) 
                or isinstance(self._clock_config, EventDrivenClockConfig)
                ) and ignored is not None:
                for dst, src, content in ignored:
                    await self.manager_inbox.put((dst,src,content))

    async def sense(self, statuses: list) -> list:
        # initiate senses array
        senses = []

        # check status of previously performed tasks
        completed = []
        for action, status in statuses:
            # sense and compile updated task status for planner 
            action : AgentAction
            status : str
            msg = AgentActionMessage(   self.get_element_name(), 
                                        self.get_element_name(), 
                                        action.to_dict(),
                                        status)
            senses.append(msg)      

            # compile completed tasks for state tracking
            if status == AgentAction.COMPLETED:
                completed.append(action.id)

        # update state
        self.state.update_state(self.get_current_time(), 
                                tasks_performed=completed, 
                                status=SimulationAgentState.SENSING)

        # inform environment of new state
        state_msg = AgentStateMessage(  self.get_element_name(), 
                                        SimulationElementRoles.ENVIRONMENT.value,
                                        self.state.to_dict()
                                    )
        await self.send_peer_message(state_msg)

        # save state as sensed state
        state_msg.dst = self.get_element_name()
        senses.append(state_msg)

        # handle environment updates
        while True:
            # wait for environment messages
            _, _, content = await self.environment_inbox.get()

            if content['msg_type'] == SimulationMessageTypes.CONNECTIVITY_UPDATE.value:
                # update connectivity
                msg = AgentConnectivityUpdate(**content)
                if msg.connected == 1:
                    self.subscribe_to_broadcasts(msg.target)
                else:
                    self.unsubscribe_to_broadcasts(msg.target)

            elif content['msg_type'] == SimulationMessageTypes.TASK_REQ.value:
                # save as senses to forward to planner
                senses.append(TaskRequest(**content))

            elif content['msg_type'] == NodeMessageTypes.RECEPTION_ACK.value:
                # no relevant information was sent by the environment
                break
                
            # give environment time to continue sending any pending messages if any are yet to be transmitted
            await asyncio.sleep(0.01)

            if self.manager_inbox.empty():
                break
        
        # handle peer broadcasts
        while not self.external_inbox.empty():
            _, _, content = await self.external_inbox.get()

            if content['msg_type'] == SimulationMessageTypes.AGENT_STATE.value:
                # save as senses to forward to planner
                senses.append(AgentStateMessage(**content))

            elif content['msg_type'] == SimulationMessageTypes.TASK_REQ.value:
                # save as senses to forward to planner
                senses.append(TaskRequest(**content))

            elif content['msg_type'] == SimulationMessageTypes.PLANNER_RESULTS.value:
                # save as senses to forward to planner
                senses.append(PlannerResultsMessage(**content))

        return senses

    async def think(self, senses: list) -> list:
        # send all sensed messages to planner
        self.log(f'sending {len(senses)} senses to planning module...')
        for sense in senses:
            sense : SimulationMessage
            sense.src = self.get_element_name()
            sense.dst = self.get_element_name()
            await self.send_internal_message(sense)

        # wait for planner to send list of tasks to perform
        self.log(f'senses sent! waiting on response from planner module...')
        actions = []
        
        while len(actions) == 0:
            _, _, content = await self.internal_inbox.get()
            
            if content['msg_type'] == SimulationMessageTypes.PLAN.value:
                msg = PlanMessage(**content)
                for action_dict in msg.plan:
                    self.log(f"received an action of type {action_dict['action_type']}")
                    actions.append(action_dict)  
        
        self.log(f"plan of {len(actions)} actions received from planner module!")
        return actions

    async def do(self, actions: list) -> dict:
        statuses = []
        self.log(f'performing {len(actions)} actions')
        
        for action_dict in actions:
            action_dict : dict
            action = AgentAction(**action_dict)

            if self.get_current_time() < action.t_start:
                self.log(f"action of type {action_dict['action_type']} has NOT started yet. waiting for start time...", level=logging.INFO)
                statuses.append((action, AgentAction.PENDING))
                
            elif action.t_end < self.get_current_time():
                self.log(f"action of type {action_dict['action_type']} has already occureed. could not perform task before...", level=logging.INFO)
                statuses.append((action, AgentAction.ABORTED))
                
            else:
                self.log(f"performing action of type {action_dict['action_type']}...", level=logging.INFO)    
                if action_dict['action_type'] == ActionTypes.PEER_MSG.value:
                    # unpack action
                    action = PeerMessageAction(**action_dict)

                    # perform action
                    self.state.update_state(self.get_current_time(), status=SimulationAgentState.MESSAGING)
                    await self.send_peer_message(action.msg)
                    
                    # update action completion status
                    action.status = AgentAction.COMPLETED
                    
                elif action_dict['action_type'] == ActionTypes.BROADCAST_MSG.value:
                    # unpack action
                    action = BroadcastMessageAction(**action_dict)

                    # perform action
                    self.state.update_state(self.get_current_time(), status=SimulationAgentState.MESSAGING)
                    await self.send_peer_broadcast(action.msg)
                    
                    # update action completion status
                    action.status = AgentAction.COMPLETED
                
                elif action_dict['action_type'] == ActionTypes.IDLE.value:
                    # unpack action 
                    action = IdleAction(**action_dict)

                    # perform action
                    self.state.update_state(self.get_current_time(), status=SimulationAgentState.IDLING)
                    delay = action.t_end - self.get_current_time()
                    await self.sim_wait(delay)

                    # update action completion status
                    if self.get_current_time() >= action.t_end:
                        action.status = AgentAction.COMPLETED
                    else:
                        action.status = AgentAction.PENDING

                elif action_dict['action_type'] == ActionTypes.MOVE.value:
                    # unpack action 
                    action = MoveAction(**action_dict)

                    # perform action
                    ## calculate new direction 
                    dx = action.pos[0] - self.state.pos[0]
                    dy = action.pos[1] - self.state.pos[1]

                    norm = math.sqrt(dx**2 + dy**2)

                    if isinstance(self._clock_config, FixedTimesStepClockConfig):
                        eps = self.state.v_max * self._clock_config.dt / 2.0
                    else:
                        eps = 1e-6

                    if norm < eps:
                        self.log('agent has reached its desired position. stopping.', level=logging.DEBUG)
                        ## stop agent 
                        new_vel = [ 0.0, 
                                    0.0]
                        self.state.update_state(self.get_current_time(), vel = new_vel, status=SimulationAgentState.TRAVELING)

                        # update action completion status
                        action.status = AgentAction.COMPLETED
                    else:
                        ## change velocity towards destination
                        dx = dx / norm
                        dy = dy / norm

                        new_vel = [ dx*self.state.v_max, 
                                    dy*self.state.v_max]

                        self.log(f'agent has NOT reached its desired position. updating velocity to {new_vel}', level=logging.DEBUG)
                        self.state.update_state(self.get_current_time(), vel = new_vel, status=SimulationAgentState.TRAVELING)

                        ## wait until destination is reached
                        delay = norm / self.state.v_max
                        await self.sim_wait(delay)
                        
                        # update action completion status
                        action.status = AgentAction.PENDING
                
                elif action_dict['action_type'] == ActionTypes.MEASURE.value:
                    # unpack action 
                    task = MeasurementTask(**action_dict)

                    # perform action
                    self.state : SimulationAgentState
                    dx = task.pos[0] - self.state.pos[0]
                    dy = task.pos[1] - self.state.pos[1]

                    norm = math.sqrt(dx**2 + dy**2)

                    ## Check if point has been reached
                    if isinstance(self._clock_config, FixedTimesStepClockConfig):
                        eps = self.state.v_max * self._clock_config.dt / 2.0
                    else:
                        eps = 1e-6

                    if norm < eps:
                        ### agent has reached its desired position
                        # perform measurement
                        self.state.update_state(self.get_current_time(), status=SimulationAgentState.MEASURING)
                        
                        await self.sim_wait(task.duration)  # TODO communicate with environment and obtain measurement information

                        # update action completion status
                        action.status = AgentAction.COMPLETED

                    else:
                        ### agent has NOT reached its desired position
                        # update action completion status
                        action.status = AgentAction.PENDING

                else:
                    # ignore action
                    self.log(f"action of type {action_dict['action_type']} not yet supported. ignoring...", level=logging.INFO)
                    action.status = AgentAction.ABORTED  
                    
                self.log(f"finished performing action of type {action_dict['action_type']}! action completion status: {action.status}", level=logging.INFO)
                statuses.append((action, action.status))

        self.log(f'returning {len(statuses)} statuses')
        return statuses
