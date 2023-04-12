
from enum import Enum
from typing import Union
from states import SimulationAgentState

from tasks import AgentTask
from dmas.messages import SimulationMessage, SimulationElementRoles

class SimulationMessageTypes(Enum):
    TASK_REQ = 'TASK_REQUEST'
    AGENT_STATE = 'AGENT_STATE'
    CONNECTIVITY_UPDATE = 'CONNECTIVITY_UPDATE'

class AgentStateMessage(SimulationMessage):
    """
    ## Tic Request Message

    Request from agents indicating that they are waiting for the next time-step advance

    ### Attributes:
        - src (`str`): name of the agent sending this message
        - dst (`str`): name of the intended simulation element to receive this message
        - msg_type (`str`): type of message being sent
        - id (`str`) : Universally Unique IDentifier for this message
        - state (`dict`): dictionary discribing the state of the agent sending this message
    """
    def __init__(self, 
                src: str, 
                dst: str, 
                state : dict,
                id: str = None, 
                **_):
        super().__init__(src, dst, SimulationMessageTypes.AGENT_STATE.value, id)
        self.state = SimulationAgentState(**state)

class AgentConnectivityUpdate(SimulationMessage):
    """
    ## Agent Connectivity Update Message

    Informs an agent that it's connectivity to another agent has changed

    ### Attributes:
        - src (`str`): name of the agent sending this message
        - dst (`str`): name of the intended agent set to receive this message
        - target (`str`): name of the agent that the destination agent will change its connectivity with
        - connected (`bool`): status of the connection between `dst` and `target`
        - msg_type (`str`): type of message being sent
        - id (`str`) : Universally Unique IDentifier for this message
        - state (`dict`): dictionary discribing the state of the agent sending this message
    """
    def __init__(self, dst: str, target : str, connected : bool, id: str = None):
        super().__init__(SimulationElementRoles.ENVIRONMENT.value, 
                         dst, 
                         SimulationMessageTypes.CONNECTIVITY_UPDATE.value, 
                         id)
        self.target = target
        self.connected = connected

class TaskRequest(SimulationMessage):
    """
    ## Task Request Message 

    Describes a task request being between simulation elements

    ### Attributes:
        - src (`str`): name of the simulation element sending this message
        - dst (`str`): name of the intended simulation element to receive this message
        - msg_type (`str`): type of message being sent
        - id (`str`) : Universally Unique IDentifier for this message
    """
    def __init__(self, src: str, dst: str, task : dict, id: str = None, **kwargs):
        super().__init__(src, dst, SimulationMessageTypes.TASK_REQ.value, id)
        self.task = task
