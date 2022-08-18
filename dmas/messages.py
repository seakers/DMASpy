from abc import abstractclassmethod
from enum import Enum


class MessageTypes(Enum):
    @abstractclassmethod
    def format_check(msg: dict):
        """
        Checks if a message of type request contains the proper contents and format.
        Returns a boolean that indicates if this message meets these criterea.
        """
        pass

class BroadcastTypes(Enum):
    """
    Types of broadcasts sent from the environemnt to all agents.
        1- tic: informs all agents of environment server's current time
        2- eclipse_event: informs agents that an agent has entered eclipse. agents must ignore transmission if they are not the agent affected by the event
        3- sim_start: notifies all agents that the simulation has started
        4- sim_end: notifies all agents that the simulation has ended 
    """
    TIC = 'TIC'
    ECLIPSE_EVENT = 'ECLIPSE_EVENT'
    ACCESS_EVENT = 'ACCESS_EVENT'
    SIM_START = 'SIM_START'
    SIM_END = 'SIM_END'

    def format_check(msg: dict):
        """
        Checks if a message of type request contains the proper contents and format.
        Returns a boolean that indicates if this message meets these criterea.
        """

        msg_src = msg.get('src', None)
        msg_dst = msg.get('dst', None)
        msg_type = msg.get('@type', None)

        if msg_src is None or msg_dst is None or msg_type is None:
            # any message must contain a source, destination, and type.
            return False
        
        if BroadcastTypes[msg_type] is BroadcastTypes.TIC:
            t = msg.get('server_clock', None)
            
            if t is None:
                # tic broadcasts must contain current server time
                return False
        elif BroadcastTypes[msg_type] is BroadcastTypes.SIM_START or BroadcastTypes[msg_type] is BroadcastTypes.SIM_END:
            return True
        elif BroadcastTypes[msg_type] is BroadcastTypes.ECLIPSE_EVENT:
            return True
        else:
            return False
        
        return True

class RequestTypes(Enum):
    """
    Types of requests between agents and environment.
        1- tic_requests: agents ask to be notified when a certain time has passed in the environment's clock    
        2- access_request: agent asks to be notified when a ground point or an agent is going to be accessible by said agent
        3- agent_information_request: agent asks for information regarding its current position, velocity, and eclipse
        4- observation_request: agent requests environment information regarding a the state of a ground point
    """
    SYNC_REQUEST = 'SYNC_REQUEST'
    TIC_REQUEST = 'TIC_REQUEST'
    ACCESS_REQUEST = 'ACCESS_REQUEST'
    AGENT_INFO_REQUEST = 'AGENT_INFO_REQUEST'
    OBSERVATION_REQUEST = 'OBSERVATION_REQUEST'
    END_CONFIRMATION = 'END_CONFIRMATION'

    def format_check(msg: dict):
        """
        Checks if a message of type request contains the proper contents and format.
        Returns a boolean that indicates if this message meets these criterea.
        """

        msg_src = msg.get('src', None)
        msg_dst = msg.get('dst', None)
        msg_type = msg.get('@type', None)

        if msg_src is None or msg_dst is None or msg_type is None:
            # any message must contain a source, destination, and type.
            return False
        
        if RequestTypes[msg_type] is RequestTypes.SYNC_REQUEST:
            port = msg.get('port', None)
            n_coroutines = msg.get('n_coroutines', None)

            if port is None or n_coroutines is None or n_coroutines < 0:
                # sync requests must contain 
                return False
        elif RequestTypes[msg_type] is RequestTypes.TIC_REQUEST:
            t_end = msg.get('t', None)
            
            if t_end is None:
                return False
        elif RequestTypes[msg_type] is RequestTypes.ACCESS_REQUEST:
            pass
        elif RequestTypes[msg_type] is RequestTypes.AGENT_INFO_REQUEST:
            pass
        elif RequestTypes[msg_type] is RequestTypes.OBSERVATION_REQUEST:
            pass
        else:
            return False
        
        return True