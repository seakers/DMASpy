import asyncio
import numpy as np
import logging
from modules import Module
from messages import *
from neo4j import GraphDatabase
from utils import PlanningSubmoduleTypes
from orbitdata import OrbitData
from tasks import MeasurementRequest

class PlanningModule(Module):
    def __init__(self, parent_agent : Module, scenario_dir : str) -> None:
        super().__init__(AgentModuleTypes.PLANNING_MODULE.value, parent_agent, [], 0)
        self.scenario_dir = scenario_dir
        self.submodules = [
            InstrumentCapabilityModule(self),
            ObservationPlanningModule(self),
            OperationsPlanningModule(self),
            PredictiveModelsModule(self),
            MeasurementPerformanceModule(self)
        ]

    async def internal_message_handler(self, msg: InternalMessage):
        """
        Handles message intended for this module and performs actions accordingly.
        """
        try:
            dst_name = msg.dst_module
            if dst_name != self.name:
                # This module is NOT the intended receiver for this message. Forwarding to rightful destination
                await self.send_internal_message(msg)
            else:
                # This module is the intended receiver for this message. Handling message
                if isinstance(msg.content, MeasurementRequest):
                    # if a measurement request is received, forward to instrument capability submodule
                    self.log(f'Received measurement request from \'{msg.src_module}\'!', level=logging.INFO)
                    msg.dst_module = PlanningSubmoduleTypes.INSTRUMENT_CAPABILITY.value

                    await self.send_internal_message(msg)

                else:
                    self.log(f'Internal messages with contents of type: {type(msg.content)} not yet supported. Discarding message.')

        except asyncio.CancelledError:
            return

class InstrumentCapabilityModule(Module):
    def __init__(self, parent_module) -> None:
        super().__init__(PlanningSubmoduleTypes.INSTRUMENT_CAPABILITY.value, parent_module, submodules=[],
                         n_timed_coroutines=0)

    async def activate(self):
        await super().activate()

    async def internal_message_handler(self, msg):
        """
        Handles message intended for this module and performs actions accordingly.
        """
        try:
            if(isinstance(msg.content, MeasurementRequest)):
                if self.queryGraphDatabase("bolt://localhost:7687", "neo4j", "ceosdb", "OLI", msg):
                    msg.dst_module = PlanningSubmoduleTypes.OBSERVATION_PLANNER.value
                    await self.send_internal_message(msg)
            else:
                self.log(f'Unsupported message type for this module.')
        except asyncio.CancelledError:
            return

    def queryGraphDatabase(self, uri, user, password, sc_name,event_msg):
        try:
            capable = False
            self.log(f'Querying knowledge graph...', level=logging.INFO)
            driver = GraphDatabase.driver(uri, auth=(user, password))
            capable = self.print_observers(driver,sc_name,event_msg)
            driver.close()
            return capable
        except Exception as e:
            print(e)
            self.log(f'Connection to Neo4j is not working! Make sure it\'s running and check the password!', level=logging.ERROR)
            return False
        

    def print_observers(self,driver,sc_name,event_msg):
        capable = False
        with driver.session() as session:
            product = "None"
            if(event_msg.content._type == "chlorophyll-a"):
                product = "Ocean chlorophyll concentration"
            observers = session.read_transaction(self.get_observers, title=product)
            for observer in observers:
                if(observer.get("name") == sc_name):
                    self.log(f'Matching instrument in knowledge graph!', level=logging.INFO)
                    capable = True
        return capable


    @staticmethod
    def get_observers(tx, title): # (1)
        result = tx.run("""
            MATCH (p:Sensor)-[r:OBSERVES]->(:ObservableProperty {name: $title})
            RETURN p
        """, title=title)

        # Access the `p` value from each record
        return [ record["p"] for record in result ]

class ObservationPlanningModule(Module):
    def __init__(self, parent_module : Module) -> None:
        self.obs_plan = []
        self.orbit_data: dict = OrbitData.from_directory(parent_module.scenario_dir)
        self.orbit_data = self.orbit_data[parent_module.parent_module.name]
        super().__init__(PlanningSubmoduleTypes.OBSERVATION_PLANNER.value, parent_module)

    async def activate(self):
        await super().activate()
        
        # Initialize observation list and plan
        self.obs_list = asyncio.Queue()

        await self.initialize_plan()

    async def initialize_plan(self):
        # this is just for testing!
        initial_obs = ObservationPlannerTask(0.0,-32.0,1.0,["OLI"],0.0,1.0)
        await self.obs_list.put(initial_obs)

    async def internal_message_handler(self, msg):
        """
        Handles message intended for this module and performs actions accordingly.
        """
        try:
            if(isinstance(msg.content, MeasurementRequest)):
                meas_req = msg.content
                new_obs = ObservationPlannerTask(meas_req._target[0],meas_req._target[1],meas_req._science_val,["OLI"],0.0,1.0)
                await self.obs_list.put(new_obs)
        except asyncio.CancelledError:
            return

    async def coroutines(self):
        coroutines = []

        try:
            ## Internal coroutines
            create_plan = asyncio.create_task(self.create_plan())
            create_plan.set_name (f'{self.name}_create_plan')
            coroutines.append(create_plan)

            # wait for the first coroutine to complete
            _, pending = await asyncio.wait(coroutines, return_when=asyncio.FIRST_COMPLETED)
            
            done_name = None
            for coroutine in coroutines:
                if coroutine not in pending:
                    done_name = coroutine.get_name()

            # cancel all other coroutine tasks
            self.log(f'{done_name} Coroutine ended. Terminating all other coroutines...', level=logging.INFO)
            for subroutine in pending:
                subroutine : asyncio.Task
                subroutine.cancel()
                await subroutine
        
        except asyncio.CancelledError:
            for coroutine in coroutines:
                coroutine : asyncio.Task
                if not coroutine.done():
                    coroutine.cancel()
                    await coroutine


    async def create_plan(self):
        try:
            while True:
                # wait for observation request 
                obs = await self.obs_list.get()
                obs_candidates = []
                # estimate next observation opportunities
                gp_accesses = self.orbit_data.get_ground_point_accesses_future(0.0, -32.0, self.get_current_time())
                gp_access_list = []
                for _, row in gp_accesses.iterrows():
                    gp_access_list.append(row)
                #print(gp_accesses)
                if(len(gp_accesses) != 0):
                    obs.start = gp_access_list[0]['time index']
                    obs.end = obs.start + 5
                    obs_candidates.append(obs)
                self.obs_plan = self.rule_based_planner(obs_candidates)
                # schedule observation plan and send to operations planner for further development
                plan_msg = InternalMessage(self.name, PlanningSubmoduleTypes.OPERATIONS_PLANNER.value, self.obs_plan)
                await self.parent_module.send_internal_message(plan_msg)

        except asyncio.CancelledError:
            return

    def rule_based_planner(self,obs_list):
        rule_based_plan = []
        estimated_reward = 100000.0
        while len(obs_list) > 0:
            best_obs = None
            maximum = 0.0
            for obs in obs_list:
                rho = (86400.0 - obs.end)/86400.0
                e = pow(rho,0.99) * estimated_reward
                adjusted_reward = obs.science_val + e
                if(adjusted_reward > maximum):
                    maximum = adjusted_reward
                    best_obs = obs
            rule_based_plan.append(best_obs)
            obs_list.remove(best_obs)
        return rule_based_plan

            

class OperationsPlanningModule(Module):
    def __init__(self, parent_module) -> None:
        super().__init__(PlanningSubmoduleTypes.OPERATIONS_PLANNER.value, parent_module, submodules=[],
                         n_timed_coroutines=1)
        self.ops_plan = []

    async def activate(self):
        await super().activate()
        self.obs_plan = asyncio.Queue()


    async def internal_message_handler(self, msg):
        """
        Handles message intended for this module and performs actions accordingly.
        """
        try:
            if(msg.src_module==PlanningSubmoduleTypes.OBSERVATION_PLANNER.value):
                await self.obs_plan.put(msg.content)
            else:
                self.log(f'Unsupported message type for this module.)')
        except asyncio.CancelledError:
            return

    async def coroutines(self):
        coroutines = []

        try:
            ## Internal coroutines
            create_ops_plan = asyncio.create_task(self.create_ops_plan())
            create_ops_plan.set_name (f'{self.name}_create_ops_plan')
            coroutines.append(create_ops_plan)

            execute_ops_plan = asyncio.create_task(self.execute_ops_plan())
            execute_ops_plan.set_name (f'{self.name}_execute_ops_plan')
            coroutines.append(execute_ops_plan)

            # wait for the first coroutine to complete
            _, pending = await asyncio.wait(coroutines, return_when=asyncio.FIRST_COMPLETED)
            
            done_name = None
            for coroutine in coroutines:
                if coroutine not in pending:
                    done_name = coroutine.get_name()

            # cancel all other coroutine tasks
            self.log(f'{done_name} Coroutine ended. Terminating all other coroutines...', level=logging.INFO)
            for subroutine in pending:
                subroutine : asyncio.Task
                subroutine.cancel()
                await subroutine
        
        except asyncio.CancelledError:
            if len(coroutines) > 0:
                for coroutine in coroutines:
                    coroutine : asyncio.Task
                    if not coroutine.done():
                        coroutine.cancel()
                        await coroutine


    async def create_ops_plan(self):
        try:
            while True:
                # Replace with basic module that adds charging to plan
                plan = await self.obs_plan.get()
                plan_beginning = self.get_current_time()
                starts = []
                ends = []
                for obs in plan:
                    starts.append(obs.start)
                    ends.append(obs.end)
                charge_task = ChargePlannerTask(plan_beginning,starts[0])
                self.ops_plan.append(charge_task)
                for i in range(len(starts)):
                    if(i+1 < len(starts)):
                        charge_task = ChargePlannerTask(ends[i],starts[i+1])
                        self.ops_plan.append(charge_task)
                    obs_task = plan[i]
                    self.ops_plan.append(obs_task)
        except asyncio.CancelledError:
            return
    
    async def execute_ops_plan(self):
        try:
            while True:
                # Replace with basic module that adds charging to plan
                curr_time = self.get_current_time()
                for task in self.ops_plan:
                    if(isinstance(task,ObservationPlannerTask)):
                        if(5 < curr_time < 10): # TODO should be between task start and task end but this is for testing
                            obs_task = ObservationTask(task.target[0], task.target[1], [InstrumentNames.TEST.value], [1])
                            msg = PlatformTaskMessage(self.name, AgentModuleTypes.ENGINEERING_MODULE.value, obs_task)
                            await self.send_internal_message(msg)
                    else:
                        self.log(f'Currently unsupported task type!')
                await self.sim_wait(1.0)
        except asyncio.CancelledError:
            return

class PredictiveModelsModule(Module):
    def __init__(self, parent_module) -> None:
        self.agent_state = None
        self.obs_plan = None
        self.ops_plan = None
        super().__init__(PlanningSubmoduleTypes.PREDICTIVE_MODEL.value, parent_module, submodules=[],
                         n_timed_coroutines=1)

    # async def activate(self):
    #     await super().activate()

    async def internal_message_handler(self, msg):
        """
        Handles message intended for this module and performs actions accordingly.
        """
        try:
            if(msg.src_module == PlanningSubmoduleTypes.OBSERVATION_PLANNER.value):
                self.obs_plan = msg.content
            elif(msg.src_module == PlanningSubmoduleTypes.OPERATIONS_PLANNER.value):
                self.ops_plan = msg.content
            else:
                self.log(f'Message from unsupported module.')
        except asyncio.CancelledError:
            return

    async def coroutines(self):
        coroutines = []

        try:
            ## Internal coroutines
            predict_state = asyncio.create_task(self.predict_state())
            predict_state.set_name (f'{self.name}_predict_state')
            coroutines.append(predict_state)

            # wait for the first coroutine to complete
            _, pending = await asyncio.wait(coroutines, return_when=asyncio.FIRST_COMPLETED)
            
            done_name = None
            for coroutine in coroutines:
                if coroutine not in pending:
                    done_name = coroutine.get_name()

            # cancel all other coroutine tasks
            self.log(f'{done_name} Coroutine ended. Terminating all other coroutines...', level=logging.INFO)
            for subroutine in pending:                
                subroutine : asyncio.Task
                subroutine.cancel()
                await subroutine
        
        except asyncio.CancelledError:
            if len(coroutines) > 0:
                for coroutine in coroutines:
                    coroutine : asyncio.Task
                    if not coroutine.done():
                        coroutine.cancel()
                        await coroutine

    async def predict_state(self):
        try:
            while True:
                if(self.obs_plan is not None):
                    plan_msg = InternalMessage(self.name, PlanningSubmoduleTypes.MEASUREMENT_PERFORMANCE.value, self.obs_plan)
                    await self.parent_module.send_internal_message(plan_msg)
                await self.sim_wait(1.0)
        except asyncio.CancelledError:
            return

class MeasurementPerformanceModule(Module):
    def __init__(self, parent_module) -> None:
        self.plan = None
        super().__init__(PlanningSubmoduleTypes.MEASUREMENT_PERFORMANCE.value, parent_module, submodules=[],
                         n_timed_coroutines=1)

    # async def activate(self):
    #     await super().activate()

    async def internal_message_handler(self, msg):
        """
        Handles message intended for this module and performs actions accordingly.
        """
        try:
            if(msg.src_module == PlanningSubmoduleTypes.PREDICTIVE_MODEL.value):
                self.plan = msg.content
            else:
                self.log(f'Unsupported message type for this module.')
        except asyncio.CancelledError:
            return

    async def coroutines(self):
        coroutines = []

        try:
            ## Internal coroutines
            evaluate_performance = asyncio.create_task(self.evaluate_performance())
            evaluate_performance.set_name (f'{self.name}_evaluate_performance')
            coroutines.append(evaluate_performance)

            # wait for the first coroutine to complete
            _, pending = await asyncio.wait(coroutines, return_when=asyncio.FIRST_COMPLETED)
            
            done_name = None
            for coroutine in coroutines:
                if coroutine not in pending:
                    done_name = coroutine.get_name()

            # cancel all other coroutine tasks
            self.log(f'{done_name} Coroutine ended. Terminating all other coroutines...', level=logging.INFO)
            for subroutine in pending:
                subroutine : asyncio.Task
                subroutine.cancel()
                await subroutine

        except asyncio.CancelledError:
            if len(coroutines) > 0:
                for coroutine in coroutines:
                    coroutine : asyncio.Task
                    if not coroutine.done():
                        coroutine.cancel()
                        await coroutine


    async def evaluate_performance(self):
        try:
            while True:
                if(self.plan is not None):
                    for i in range(len(self.plan)):
                        event = self.plan[i]
                        observation_time = 20.0
                        delta = observation_time - float(event.content["time"])
                        lagfunc = -0.08182 * np.log(delta)+0.63182 # from molly's ppt on google drive
                        event.content["meas_perf_value"] = lagfunc
                        self.plan[i] = event
                    plan_msg = InternalMessage(self.name, PlanningSubmoduleTypes.OBSERVATION_PLANNER.value, self.plan)
                    await self.parent_module.send_internal_message(plan_msg)
                await self.sim_wait(1.0)

        except asyncio.CancelledError:
            return