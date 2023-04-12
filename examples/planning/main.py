from datetime import datetime
import logging
import os, shutil
import random
import numpy as np
import zmq
import concurrent.futures

from dmas.clocks import FixedTimesStepClockConfig
from dmas.elements import SimulationElement
from dmas.messages import SimulationElementRoles
from dmas.network import NetworkConfig

from tasks import Task
from manager import PlanningSimulationManager
from monitor import ResultsMonitor
from environment import SimulationEnvironment
from agent import SimulationAgent
from planners import PlannerTypes

def setup_results_directory(scenario_name) -> str:
    """
    Creates an empty results directory within the `mccbba` directory
    """
    results_path = f'./{scenario_name}'

    if not os.path.exists(results_path):
        # create results directory if it doesn't exist
        os.makedirs(results_path)
    else:
        # clear results in case it already exists
        results_path
        for filename in os.listdir(results_path):
            file_path = os.path.join(results_path, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print('Failed to delete %s. Reason: %s' % (file_path, e))

def create_tasks():
    pass

if __name__ == '__main__':
    """
    Wrapper for planner simulation using DMAS
    """    
    # create results directory
    scenario_name = 'TEST'
    results_path = setup_results_directory(scenario_name)
    
    # define simulation config
    ## environment bounds
    x_bounds = [0, 10]
    y_bounds = [0, 10]
    comms_range = 5

    ## agents
    n_agents = 2

    ## clock configuration
    year = 2023
    month = 1
    day = 1
    hh = 12
    mm = 00
    ss = 00
    start_date = datetime(year, month, day, hh, mm, ss)
    end_date = datetime(year, month, day, hh, mm, ss+10)
    dt = 1.0
    clock_config = FixedTimesStepClockConfig(start_date, end_date, dt)
    
    ## create tasks
    ### random tasks 
    n_tasks = 10
    task_types = ['VNIR', 'MWR', 'LIDAR']
    tasks = []
    for i in range(n_tasks):
        t_start = random.random() * clock_config.get_total_seconds()
        t_end = random.random() * (clock_config.get_total_seconds() - t_start)
        x = x_bounds[0] + (x_bounds[1] - x_bounds[0]) * random.random()
        y = y_bounds[0] + (y_bounds[1] - y_bounds[0]) * random.random()
        pos = [x, y]
        s_max = 1.0
        
        instruments = []
        n_instruments = random.randint(1, len(task_types))
        for _ in range(n_instruments):
            i_ins = random.randint(0, len(task_types)-1)
            while task_types[i_ins] in instruments:
                i_ins = random.randint(0, len(task_types)-1)
            instruments.append(task_types[i_ins])           

        task = Task(pos, s_max, instruments, t_start, t_end)
        tasks.append(Task(pos, s_max, instruments, t_start, t_end))

    # create simulation manager
    port = 5555
    level = logging.WARNING
    network_name = 'PLANNING_NETWORK'
    manager_network_config = NetworkConfig( network_name,
											manager_address_map = {
																	zmq.REP: [f'tcp://*:{port}'],
																	zmq.PUB: [f'tcp://*:{port+1}'],
																	zmq.PUSH: [f'tcp://localhost:{port+2}']
                                                                    }
                                            )
    node_names = [f'AGENT_{i}' for i in range(n_agents)]
    node_names.append(SimulationElementRoles.ENVIRONMENT.value)
    manager = PlanningSimulationManager(node_names, clock_config, manager_network_config, level)
    logger = manager.get_logger()

    # create results monitor
    monitor_network_config = NetworkConfig( network_name,
                                    external_address_map = {zmq.SUB: [f'tcp://localhost:{port+1}'],
                                                            zmq.PULL: [f'tcp://*:{port+2}']}
                                    )
    
    monitor = ResultsMonitor(clock_config, monitor_network_config, logger=logger)

    # create simulation environment
    env_network_config = NetworkConfig( manager.get_network_config().network_name,
											manager_address_map = {
													zmq.REQ: [f'tcp://localhost:{port}'],
													zmq.SUB: [f'tcp://localhost:{port+1}'],
													zmq.PUSH: [f'tcp://localhost:{port+2}']},
											external_address_map = {
													zmq.REP: [f'tcp://*:{port+3}'],
													zmq.PUB: [f'tcp://*:{port+4}']
											})
    
    environment = SimulationEnvironment(env_network_config, manager_network_config, x_bounds, y_bounds, comms_range, tasks, logger=logger)

    # create simulation agents
    agents = []
    for id in range(n_agents):        
        agent = SimulationAgent(    network_name,
                                    port, 
                                    id,
                                    manager_network_config,
                                    planner_type=PlannerTypes.ACCBBA
                                    )


    # run simulation
    # with concurrent.futures.ThreadPoolExecutor(len(agents) + 3) as pool:
    #     pool.submit(monitor.run, *[])
    #     pool.submit(manager.run, *[])
    #     pool.submit(environment.run, *[])
    #     for agent in agents:                
    #         agent : SimulationElement
    #         pool.submit(agent.run, *[])

    # compile results from monitor

    # print results

