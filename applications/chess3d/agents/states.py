from typing import Union
import numpy as np
from dmas.agents import AbstractAgentState

class SimulationAgentState(AbstractAgentState):
    """
    Describes the state of a 3D-CHESS agent
    """
    
    IDLING = 'IDLING'
    TRAVELING = 'TRAVELING'
    MANEUVERING = 'MANEUVERING'
    MEASURING = 'MEASURING'
    SENSING = 'SENSING'
    THINKING = 'THINKING'
    LISTENING = 'LISTENING'

    def __init__(   self, 
                    pos : list,
                    vel : list,
                    status : str,
                    t : Union[float, int]=0,
                    **_
                ) -> None:
        super().__init__()
        self.status = status
        self.t = t
    
    def __repr__(self) -> str:
        return str(self.to_dict())

    def __str__(self):
        return str(dict(self.__dict__))
    
    def to_dict(self) -> dict:
        return self.__dict__


