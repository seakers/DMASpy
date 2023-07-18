import asyncio
import logging
import math
from typing import Any, Callable
import pandas as pd

import zmq
from nodes.orbitdata import OrbitData
from nodes.science.reqs import GroundPointMeasurementRequest, MeasurementRequetTypes
from nodes.planning.planners import Bid
from dmas.network import NetworkConfig
from nodes.science.reqs import MeasurementRequest
from nodes.states import *
from applications.planning.actions import WaitForMessages
from dmas.agents import AgentAction
from messages import *
from nodes.planning.planners import PlanningModule


class GreedyBid(Bid):
    """
    ## Bid for Greedy planner

    Describes a bid placed on a measurement request by a given agent

    ### Attributes:
        - req (`dict`): measurement request being bid on
        - req_id (`str`): id of the request being bid on
        - subtask_index (`int`) : index of the subtask to be bid on
        - main_measurement (`str`): name of the main measurement assigned by this subtask bid
        - bidder (`bidder`): name of the agent keeping track of this bid information
        - own_bid (`float` or `int`): latest bid from bidder
        - winner (`str`): name of current the winning agent
        - winning_bid (`float` or `int`): current winning bid
        - t_img (`float` or `int`): time where the task is set to be performed by the winning agent
        - t_update (`float` or `int`): latest time when this bid was updated
    """
    def __init__(
                    self, 
                    req: dict, 
                    subtask_index : int,
                    main_measurement : str,
                    bidder: str, 
                    winning_bid: Union[float, int] = 0, 
                    own_bid: Union[float, int] = 0, 
                    winner: str = Bid.NONE, 
                    t_img: Union[float, int] = -1, 
                    t_update: Union[float, int] = -1,
                    **_
                ) -> Bid:
        """
        Creates an instance of a task bid

        ### Arguments:
            - req (`dict`): measurement request being bid on
            - main_measurement (`str`): name of the main measurement assigned by this subtask bid
            - dependencies (`list`): portion of the dependency matrix related to this subtask bid
            - time_constraints (`list`): portion of the time dependency matrix related to this subtask bid
            - bidder (`bidder`): name of the agent keeping track of this bid information
            - own_bid (`float` or `int`): latest bid from bidder
            - winner (`str`): name of current the winning agent
            - winning_bid (`float` or `int`): current winning bid
            - t_img (`float` or `int`): time where the task is set to be performed by the winning agent
            - t_update (`float` or `int`): latest time when this bid was updated
        """
        super().__init__(req, bidder, winning_bid, own_bid, winner, t_img, t_update)

        self.subtask_index = subtask_index
        self.main_measurement = main_measurement
        
    def set_bid(self, new_bid : Union[int, float], t_img : Union[int, float], t_update : Union[int, float]) -> None:
        """
        Sets new values for this bid

        ### Arguments: 
            - new_bid (`int` or `float`): new bid value
            - t_img (`int` or `float`): new imaging time
            - t_update (`int` or `float`): update time
        """
        self.own_bid = new_bid
        self.winning_bid = new_bid
        self.winner = self.bidder
        self.t_img = t_img
        self.t_update = t_update

    def __str__(self) -> str:
        """
        Returns a string representation of this task bid in the following format:
        - `task_id`, `subtask_index`, `main_measurement`, `dependencies`, `bidder`, `own_bid`, `winner`, `winning_bid`, `t_img`, `t_update`
        """
        task = MeasurementRequest(**self.req)
        split_id = task.id.split('-')
        line_data = [split_id[0], self.subtask_index, self.main_measurement, self.dependencies, task.pos, self.bidder, round(self.own_bid, 3), self.winner, round(self.winning_bid, 3), round(self.t_img, 3), round(self.t_violation, 3), self.bid_solo, self.bid_any]
        out = ""
        for i in range(len(line_data)):
            line_datum = line_data[i]
            out += str(line_datum)
            if i < len(line_data) - 1:
                out += ','

        return out
    
    def copy(self) -> object:
        return GreedyBid(  **self.to_dict() )

    def subtask_bids_from_task(req : MeasurementRequest, bidder : str) -> list:
        """
        Generates subtask bids from a measurement task request
        """
        subtasks = []        
        for subtask_index in range(len(req.measurement_groups)):
            main_measurement, dependend_measurements = req.measurement_groups[subtask_index]

            if len(dependend_measurements) == 0:
                # DO NOT allow for colaboration
                subtasks.append(GreedyBid(  
                                            req.to_dict(), 
                                            subtask_index,
                                            main_measurement,
                                            bidder
                                        )
                                )
        return subtasks

    def reset(self, t_update: Union[float, int]) -> None:        
        # reset bid values
        super().reset(t_update)

    def has_winner(self) -> bool:
        """
        Checks if this bid has a winner
        """
        return self.winner != GreedyBid.NONE

    def update(self, other_dict: dict, t_update: Union[float, int]) -> object:
        other = GreedyBid(**other_dict)

        if (    other.winning_bid > self.winning_bid
            or (other.winning_bid == self.winning_bid and self._tie_breaker(self, other))
            ):
            self._update_info(other)
            
        self.t_update = t_update
        return self

    def _update_info(self, other : Bid, t_update: Union[float, int]) -> None:
        super()._update_info(other)
        self.t_update = t_update
        

    def reset(self, t: Union[float, int]) -> None:
        super().reset()
        self.t_update = t


class GreedyPlanner(PlanningModule):
    """
    Schedules masurement request tasks on a first-come, first-served basis.
    """
    def __init__(self, 
                results_path: str, 
                parent_name: str, 
                parent_network_config: NetworkConfig, 
                utility_func: Callable[[], Any], 
                payload : list,
                level: int = logging.INFO, 
                logger: logging.Logger = None) -> None:
        super().__init__(results_path, parent_name, parent_network_config, utility_func, level, logger)
        self.payload = payload
        self.parent_agent_type = None
        self.orbitdata : OrbitData = None

    async def planner(self) -> None:
        try:
            t_curr = 0
            bundle = []
            path = []
            results = {}

            while True:
                plan_out = []
                state_msg : AgentStateMessage = await self.states_inbox.get()

                # update current time:
                state = SimulationAgentState.from_dict(state_msg.state)
                if self.parent_agent_type is None:
                    if isinstance(state, SatelliteAgentState):
                        # import orbit data
                        self.orbitdata : OrbitData = self._load_orbit_data()
                        self.parent_agent_type = SimulationAgentTypes.SATELLITE.value
                    elif isinstance(state, UAVAgentState):
                        self.parent_agent_type = SimulationAgentTypes.UAV.value
                    else:
                        raise NotImplementedError(f"states of type {state_msg.state['state_type']} not supported for greedy planners.")

                if t_curr < state.t:
                    t_curr = state.t

                while not self.action_status_inbox.empty():
                    action_msg : AgentActionMessage = await self.action_status_inbox.get()

                    if action_msg.status == AgentAction.PENDING:
                        # if action wasn't completed, re-try
                        plan_ids = [action.id for action in self.plan]
                        action_dict : dict = action_msg.action
                        if action_dict['id'] in plan_ids:
                            self.log(f'action {action_dict} not completed yet! trying again...')
                            plan_out.append(action_dict)

                    else:
                        # if action was completed or aborted, remove from plan
                        action_dict : dict = action_msg.action
                        completed_action = AgentAction(**action_dict)
                        removed = None
                        for action in self.plan:
                            action : AgentAction
                            if action.id == completed_action.id:
                                removed = action
                                break
                        
                        # print(f'\nACTIONS COMPLETED\tT{t_curr}\nid\taction type\tt_start\tt_end')
                        if removed is not None:
                            self.plan : list
                            self.plan.remove(removed)
                            removed = removed.to_dict()
                            # print(removed['id'].split('-')[0], removed['action_type'], removed['t_start'], removed['t_end'])
                        # else:
                        #     print('\n')

                while not self.measurement_req_inbox.empty(): # replan measurement plan
                    # unpack measurement request
                    req_msg : MeasurementRequestMessage = await self.measurement_req_inbox.get()
                    req = MeasurementRequest.from_dict(req_msg.req)

                    if req.id not in results:
                        # was not aware of this task; add to results as a blank bid
                        results[req.id] = GreedyBid.subtask_bids_from_task(req, self.get_parent_name())

                    results, bundle, path = self.planning_phase(state, results, bundle, path)
                    self.plan = self.plan_from_path(state, results, path)

                if len(plan_out) == 0 and len(self.plan) > 0:
                    next_action : AgentAction = self.plan[0]
                    if next_action.t_start <= t_curr:
                        plan_out.append(next_action.to_dict())

                # --- FOR DEBUGGING PURPOSES ONLY: ---
                self.log(f'\nPATH\tT{t_curr}\nid\tsubtask index\tmain mmnt\tpos\tt_img', level=logging.DEBUG)
                out = ''
                for req, subtask_index in path:
                    req : MeasurementRequest; subtask_index : int
                    bid : GreedyBid = results[req.id][subtask_index]
                    out += f"{req.id.split('-')[0]}, {subtask_index}, {bid.main_measurement}, {req.pos}, {bid.t_img}\n"
                self.log(out, level=logging.DEBUG)

                self.log(f'\nPLAN\tT{t_curr}\nid\taction type\tt_start\tt_end', level=logging.DEBUG)
                out = ''
                for action in self.plan:
                    action : AgentAction
                    out += f"{action.id.split('-')[0]}, {action.action_type}, {action.t_start}, {action.t_end},\n"
                self.log(out, level=logging.DEBUG)

                self.log(f'\nPLAN OUT\tT{t_curr}\nid\taction type\tt_start\tt_end', level=logging.DEBUG)
                out = ''
                for action in plan_out:
                    action : dict
                    out += f"{action['id'].split('-')[0]}, {action['action_type']}, {action['t_start']}, {action['t_end']}\n"
                self.log(out, level=logging.DEBUG)
                # -------------------------------------

                if len(plan_out) == 0:
                    # if no plan left, just idle for a time-step
                    self.log('no more actions to perform. instruct agent to idle for the remainder of the simulation.')
                    if len(self.plan) == 0:
                        t_idle = t_curr + 1e8 # TODO find end of simulation time        
                    else:
                        t_idle = self.plan[0].t_start
                    action = WaitForMessages(t_curr, t_idle)
                    plan_out.append(action.to_dict())
                    
                self.log(f'sending {len(plan_out)} actions to agent...')
                plan_msg = PlanMessage(self.get_element_name(), self.get_network_name(), plan_out)
                await self._send_manager_msg(plan_msg, zmq.PUB)

                self.log(f'actions sent!')

        except asyncio.CancelledError:
            return

    def planning_phase(self, state : SimulationAgentState, results : dict, bundle : list, path : list) -> tuple:
        """
        Uses the most updated measurement request information to construct a path
        """
        available_tasks : list = self.get_available_tasks(state, bundle, results)
        
        current_bids = {req.id : {} for req, _ in bundle}
        for req, subtask_index in bundle:
            req : MeasurementRequest
            current_bid : GreedyBid = results[req.id][subtask_index]
            current_bids[req.id][subtask_index] = current_bid.copy()

        max_path = [(req, subtask_index) for req, subtask_index in path]; 
        max_path_bids = {req.id : {} for req, _ in path}
        for req, subtask_index in path:
            req : MeasurementRequest
            max_path_bids[req.id][subtask_index] = results[req.id][subtask_index]

        max_utility = 0.0
        max_task = -1

        while len(available_tasks) > 0 and max_task is not None:                   
            # find next best task to put in bundle (greedy)
            max_task = None 
            max_subtask = None
            for measurement_req, subtask_index in available_tasks:
                # calculate bid for a given available task
                measurement_req : MeasurementRequest
                subtask_index : int

                if (    
                        isinstance(measurement_req, GroundPointMeasurementRequest) 
                    and isinstance(state, SatelliteAgentState)
                    ):
                    # check if the satellite can observe the GP
                    lat,lon,_ = measurement_req.pos
                    df : pd.DataFrame = self.orbitdata.get_ground_point_accesses_future(lat, lon, 0.0)
                    if df.empty:
                        continue

                projected_path, projected_bids, projected_path_utility = self.calc_path_bid(state, results, path, measurement_req, subtask_index)

                # check if path was found
                if projected_path is None:
                    continue
                
                # compare to maximum task
                bid_utility = projected_bids[measurement_req.id][subtask_index].winning_bid
                if (max_task is None 
                    # or projected_path_utility > max_path_utility
                    or bid_utility > max_utility
                    ):

                    # check for cualition and mutex satisfaction
                    proposed_bid : GreedyBid = projected_bids[measurement_req.id][subtask_index]
                    
                    max_path = projected_path
                    max_task = measurement_req
                    max_subtask = subtask_index
                    max_path_bids = projected_bids
                    max_path_utility = projected_path_utility
                    max_utility = proposed_bid.winning_bid

            if max_task is not None:
                # max bid found! place task with the best bid in the bundle and the path
                bundle.append((max_task, max_subtask))
                path = max_path

                # # remove bid task from list of available tasks
                # available_tasks.remove((max_task, max_subtask))
            
            #  update bids
            for measurement_req, subtask_index in path:
                measurement_req : MeasurementRequest
                subtask_index : int
                new_bid : GreedyBid = max_path_bids[measurement_req.id][subtask_index]

                results[measurement_req.id][subtask_index] = new_bid

            available_tasks : list = self.get_available_tasks(state, bundle, results)

        return results, bundle, path

    def get_available_tasks(self, state : SimulationAgentState, bundle : list, results : dict) -> list:
        """
        Checks if there are any tasks available to be performed

        ### Returns:
            - list containing all available and bidable tasks to be performed by the parent agent
        """
        available = []
        for req_id in results:
            for subtask_index in range(len(results[req_id])):
                subtaskbid : GreedyBid = results[req_id][subtask_index]; 
                req = MeasurementRequest.from_dict(subtaskbid.req)

                is_biddable = self.can_bid(state, req, subtask_index, results[req_id]) 
                already_in_bundle = self.check_if_in_bundle(req, subtask_index, bundle)
                already_performed = self.task_has_been_performed(results, req, subtask_index, state.t)
                
                if is_biddable and not already_in_bundle and not already_performed:
                    available.append((req, subtaskbid.subtask_index))

        return available
    
    def check_if_in_bundle(self, req : MeasurementRequest, subtask_index : int, bundle : list) -> bool:
        for req_i, subtask_index_j in bundle:
            if req_i.id == req.id and subtask_index == subtask_index_j:
                return True
    
        return False

    def can_bid(self, state : SimulationAgentState, req : MeasurementRequest, subtask_index : int, subtaskbids : list) -> bool:
        """
        Checks if an agent has the ability to bid on a measurement task
        """
        # check capabilities - TODO: Replace with knowledge graph
        subtaskbid : GreedyBid = subtaskbids[subtask_index]
        if subtaskbid.main_measurement not in [instrument.name for instrument in self.payload]:
            return False 

        # check time constraints
        ## Constraint 1: task must be able to be performed during or after the current time
        if req.t_end < state.t:
            return False
        
        return True

    def task_has_been_performed(self, results : dict, req : MeasurementRequest, subtask_index : int, t : Union[int, float]) -> bool:
        current_bid : GreedyBid = results[req.id][subtask_index]
        subtask_already_performed = t > current_bid.t_img and current_bid.winner != GreedyBid.NONE
        if subtask_already_performed:
            return True

        for subtask_bid in results[req.id]:
            subtask_bid : GreedyBid            
            if t > subtask_bid.t_img and subtask_bid.winner != GreedyBid.NONE:
                return True
        
        return False

    def calc_path_bid(
                        self, 
                        state : SimulationAgentState, 
                        original_results : dict,
                        original_path : list, 
                        req : MeasurementRequest, 
                        subtask_index : int
                    ) -> tuple:
        winning_path = None
        winning_bids = None
        winning_path_utility = 0.0

        # find best placement in path
        # self.log_task_sequence('original path', original_path, level=logging.WARNING)
        for i in range(len(original_path)+1):
            # generate possible path
            path = [scheduled_task for scheduled_task in original_path]
            
            path.insert(i, (req, subtask_index))
            # self.log_task_sequence('new proposed path', path, level=logging.WARNING)

            # calculate bids for each task in the path
            bids = {}
            for req_i, subtask_j in path:
                # calculate imaging time
                req_i : MeasurementRequest; subtask_j : int
                t_img = self.calc_imaging_time(state, path, bids, req_i, subtask_j)

                # calc utility
                params = {"req" : req_i, "subtask_index" : subtask_j, "t_img" : t_img}
                utility = self.utility_func(**params) if t_img >= 0 else 0.0

                # create bid
                bid : GreedyBid = original_results[req_i.id][subtask_j].copy()
                bid.set_bid(utility, t_img, state.t)
                
                if req_i.id not in bids:
                    bids[req_i.id] = {}    
                bids[req_i.id][subtask_j] = bid

            # look for path with the best utility
            path_utility = self.sum_path_utility(path, bids)
            if path_utility > winning_path_utility:
                winning_path = path
                winning_bids = bids
                winning_path_utility = path_utility

        return winning_path, winning_bids, winning_path_utility

    def sum_path_utility(self, path : list, bids : dict) -> float:
        utility = 0.0
        for task, subtask_index in path:
            task : MeasurementRequest
            bid : GreedyBid = bids[task.id][subtask_index]
            utility += bid.own_bid

        return utility
        
    def plan_from_path( self, 
                        state : SimulationAgentState, 
                        results : dict, 
                        path : list
                    ) -> list:
        """
        Generates a list of AgentActions from the current path.

        Agents look to move to their designated measurement target and perform the measurement.
        """

        plan = []
        for i in range(len(path)):
            measurement_req, subtask_index = path[i]
            measurement_req : MeasurementRequest; subtask_index : int
            subtask_bid : GreedyBid = results[measurement_req.id][subtask_index]

            if not isinstance(measurement_req, GroundPointMeasurementRequest):
                raise NotImplementedError(f"Cannot create plan for requests of type {type(measurement_req)}")
            
            if i == 0:
                t_prev = state.t
                prev_state = state
            else:
                prev_req, prev_subtask_index = path[i-1]
                prev_req : MeasurementRequest; prev_subtask_index : int
                bid_prev : Bid = results[prev_req.id][prev_subtask_index]
                t_prev : float = bid_prev.t_img + prev_req.duration

                if isinstance(state, SatelliteAgentState):
                    prev_state : SatelliteAgentState = state.propagate(t_prev)
                    prev_state.attitude = [
                                        prev_state.calc_off_nadir_agle(prev_req),
                                        0.0,
                                        0.0
                                    ]

                elif isinstance(state, UAVAgentState):
                    prev_state : UAVAgentState = state.copy()
                    prev_state.t = t_prev

                    if isinstance(prev_req, GroundPointMeasurementRequest):
                        prev_state.pos = prev_req.pos
                    else:
                        raise NotImplementedError(f"cannot calculate travel time start for requests of type {type(prev_req)} for uav agents")

                else:
                    raise NotImplementedError(f"cannot calculate travel time start for agent states of type {type(state)}")

            # point to target
            t_maneuver_end = None
            if isinstance(state, SatelliteAgentState):
                t_maneuver_start = prev_state.t
                tf = prev_state.calc_off_nadir_agle(measurement_req)
                t_maneuver_end = t_maneuver_start + abs(tf - prev_state.attitude[0]) / 1.0 # TODO change max attitude rate 

                if t_maneuver_start == -1.0:
                    continue
                if abs(t_maneuver_start - t_maneuver_end) >= 1e-3:
                    maneuver_action = ManeuverAction([tf, 0, 0], t_maneuver_start, t_maneuver_end)
                    plan.append(maneuver_action)            

            # move to target
            t_move_start = prev_state.t if t_maneuver_end is None else t_maneuver_end
            if isinstance(state, SatelliteAgentState):
                lat, lon, _ = measurement_req.lat_lon_pos
                df : pd.DataFrame = self.orbitdata.get_ground_point_accesses_future(lat, lon, t_move_start)
                if df.empty:
                    continue
                for _, row in df.iterrows():
                    t_move_end = row['time index'] * self.orbitdata.time_step
                    break

                future_state : SatelliteAgentState = state.propagate(t_move_end)
                final_pos = future_state.pos

            elif isinstance(state, UAVAgentState):
                final_pos = measurement_req.pos
                dr = np.array(final_pos) - np.array(prev_state.pos)
                norm = np.sqrt( dr.dot(dr) )
                
                t_move_end = t_move_start + norm / state.max_speed

            else:
                raise NotImplementedError(f"cannot calculate travel time end for agent states of type {type(state)}")
            
            t_img_start = t_move_end
            t_img_end = t_img_start + measurement_req.duration

            if isinstance(self._clock_config, FixedTimesStepClockConfig):
                dt = self._clock_config.dt
                if t_move_start < np.Inf:
                    t_move_start = dt * math.floor(t_move_start/dt)
                if t_move_end < np.Inf:
                    t_move_end = dt * math.ceil(t_move_end/dt)

                if t_img_start < np.Inf:
                    t_img_start = dt * math.ceil(t_img_start/dt)
                if t_img_end < np.Inf:
                    t_img_end = dt * math.ceil((t_img_start + measurement_req.duration)/dt)
            
            if abs(t_move_start - t_move_end) >= 1e-3:
                move_action = TravelAction(final_pos, t_move_start, t_move_end)
                plan.append(move_action)
            
            # perform measurement
            measurement_action = MeasurementAction( 
                                                    measurement_req.to_dict(),
                                                    subtask_index, 
                                                    subtask_bid.main_measurement,
                                                    subtask_bid.winning_bid,
                                                    t_img_start, 
                                                    t_img_end
                                                    )
            plan.append(measurement_action)  
        
        return plan

    async def teardown(self) -> None:
        # Nothing to teardown
        return