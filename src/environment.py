from typing import Union

from simpy import Environment, Event
from simpy.core import SimTime

from src.agents.agent import AbstractAgent
from src.orbit_data import OrbitData


class SimulationEnvironment(Environment):
    def __init__(self, initial_time: SimTime = 0):
        super().__init__(initial_time=initial_time)
        self.agent_list = []
        self.orbit_data = []

    def add_agents(self, agent_list):
        self.agent_list = agent_list
        self.orbit_data = dict.fromkeys(agent_list)
        for agent in agent_list:
            self.orbit_data[agent] = OrbitData(agent)

    def simulate(self, until: Union[SimTime, Event] = None):
        if len(self.agent_list) == 0:
            raise EnvironmentError('No agents loaded to simulation')

        for agent in self.agent_list:
            self.process(agent.live())
            self.process(agent.platform.sim())

        self.run(until)

        for agent in self.agent_list:
            agent.print_state()
            agent.print_planner_history()

    def is_eclipse(self, agent: AbstractAgent, t: SimTime):
        return False

    def get_position(self, agent: AbstractAgent, t: SimTime):
        return [-1, -1, -1]

    def get_velocity(self, agent: AbstractAgent, t: SimTime):
        return [-1, -1, -1]