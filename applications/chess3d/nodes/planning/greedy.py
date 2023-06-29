import asyncio
import logging
from typing import Any, Callable

import zmq
from applications.chess3d.nodes.states import GroundStationAgentState, SatelliteAgentState, SimulationAgentTypes, UAVAgentState
from applications.planning.actions import WaitForMessages
from dmas.agents import AgentAction
from dmas.modules import NetworkConfig, logging
from messages import *
from dmas.messages import ManagerMessageTypes
from nodes.planning.planners import PlanningModule


class GreedyPlanner(PlanningModule):
    async def setup(self) -> None:
        # initialize internal messaging queues
        self.states_inbox = asyncio.Queue()
        self.action_status_inbox = asyncio.Queue()
        self.measurement_req_inbox = asyncio.Queue()

    async def live(self) -> None:
        """
        Performs three concurrent tasks:
        - Listener: receives messages from the parent agent and checks results
        - Bundle-builder: plans and bids according to local information
        - Rebroadcaster: forwards plan to agent
        """
        try:
            listener_task = asyncio.create_task(self.listener(), name='listener()')
            bundle_builder_task = asyncio.create_task(self.planner(), name='planner()')
            
            tasks = [listener_task, bundle_builder_task]

            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        finally:
            for task in done:
                self.log(f'`{task.get_name()}` task finalized! Terminating all other tasks...')

            for task in pending:
                task : asyncio.Task
                if not task.done():
                    task.cancel()
                    await task


    async def listener(self) -> None:
        """
        Listens for any incoming messages, unpacks them and classifies them into 
        internal inboxes for future processing
        """
        try:
            # initiate results tracker
            results = {}

            # listen for broadcasts and place in the appropriate inboxes
            while True:
                self.log('listening to manager broadcast!')
                _, _, content = await self.listen_manager_broadcast()

                # if sim-end message, end agent `live()`
                if content['msg_type'] == ManagerMessageTypes.SIM_END.value:
                    self.log(f"received manager broadcast or type {content['msg_type']}! terminating `live()`...")
                    return

                elif content['msg_type'] == SimulationMessageTypes.SENSES.value:
                    self.log(f"received senses from parent agent!", level=logging.DEBUG)

                    # unpack message 
                    senses_msg : SensesMessage = SensesMessage(**content)

                    senses = []
                    senses.append(senses_msg.state)
                    senses.extend(senses_msg.senses)     

                    for sense in senses:
                        if sense['msg_type'] == SimulationMessageTypes.AGENT_ACTION.value:
                            # unpack message 
                            action_msg = AgentActionMessage(**sense)
                            self.log(f"received agent action of status {action_msg.status}!")
                            
                            # send to planner
                            await self.action_status_inbox.put(action_msg)

                        elif sense['msg_type'] == SimulationMessageTypes.AGENT_STATE.value:
                            # unpack message 
                            state_msg : AgentStateMessage = AgentStateMessage(**sense)
                            self.log(f"received agent state message!")
                                                        
                            # send to planner
                            await self.states_inbox.put(state_msg) 

                        elif sense['msg_type'] == SimulationMessageTypes.MEASUREMENT_REQ.value:
                            # unpack message 
                            req_msg = MeasurementRequestMessage(**sense)
                            self.log(f"received measurement request message!")
                            
                            # send to planner
                            await self.measurement_req_inbox.put(req_msg)

                        # TODO support down-linked information processing

        except asyncio.CancelledError:
            return
        
        finally:
            self.listener_results = results

    async def planne(self) -> None:
        try:
            t_curr = 0
            while True:
                plan_out = []
                msg : AgentStateMessage = await self.states_inbox.get()

                # update current time:
                if msg.state['state_type'] == SimulationAgentTypes.SATELLITE.value:
                    state = SatelliteAgentState(**msg.state)
                elif msg.state['state_type'] == SimulationAgentTypes.UAV.value:
                    state = UAVAgentState(**msg.state)
                else:
                    raise NotImplementedError(f"`state_type` {msg.state['state_type']} not supported.")

                if t_curr < state.t:
                    t_curr = state.t

                while not self.action_status_inbox.empty():
                    msg : AgentActionMessage = await self.action_status_inbox.get()

                    if msg.status != AgentAction.COMPLETED and msg.status != AgentAction.ABORTED:
                        # if action wasn't completed, re-try
                        action_dict : dict = msg.action
                        self.log(f'action {action_dict} not completed yet! trying again...')
                        plan_out.append(action_dict)

                    elif msg.status == AgentAction.COMPLETED:
                        # if action was completed, remove from plan
                        action_dict : dict = msg.action
                        completed_action = AgentAction(**action_dict)
                        removed = None
                        for action in self.plan:
                            action : AgentAction
                            if action.id == completed_action.id:
                                removed = action
                                break

                        if removed is not None:
                            self.plan.remove(removed)

                while not self.measurement_req_inbox.empty():
                    # TODO replan measurements
                    msg : MeasurementRequestMessage = await self.measurement_req_inbox.get()

                for action in self.plan:
                    action : AgentAction
                    if action.t_start <= t_curr <= action.t_end:
                        plan_out.append(action.to_dict())
                        break

                if len(plan_out) == 0:
                    # if no plan left, just idle for a time-step
                    self.log('no more actions to perform. instruct agent to idle for the remainder of the simulation.')
                    t_idle = t_curr + 1e6 # TODO find end of simulation time        
                    action = WaitForMessages(t_curr, t_idle)
                    plan_out.append(action.to_dict())
                    
                self.log(f'sending {len(plan_out)} actions to agent...')
                plan_msg = PlanMessage(self.get_element_name(), self.get_network_name(), plan_out)
                await self._send_manager_msg(plan_msg, zmq.PUB)

                self.log(f'actions sent!')

        except asyncio.CancelledError:
            return