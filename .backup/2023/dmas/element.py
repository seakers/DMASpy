from abc import ABC, abstractmethod
import asyncio
import logging
import zmq
import zmq.asyncio as azmq
import socket

from dmas.messages import SimulationMessage
from dmas.utils import *

class SimulationElement(ABC):
    """
    ## Abstract Simulation Element 

    Base class for all simulation elements. This including all agents, environment, and simulation manager.

    ### Attributes:
        - _name (`str`): The name of this simulation element
        - _network_config (:obj:`NetworkConfig`): description of the addresses pointing to this simulation element
        - _my_addresses (`list`): List of addresses used by this simulation element
        - _logger (`Logger`): debug logger

        - _pub_socket (:obj:`Socket`): The element's broadcast port socket
        - _pub_socket_lock (:obj:`Lock`): async lock for _pub_socket (:obj:`Socket`)
        - _monitor_push_socket (:obj:`Socket`): The element's monitor port socket
        - _monitor_push_socket_lock (:obj:`Lock`): async lock for _monitor_push_socket (:obj:`Socket`)

        - _clock_config (:obj:`ClockConfig`): description of this simulation's clock configuration
        - _address_ledger (`dict`): ledger containing the addresses pointing to each node's connecting ports

    ### Communications diagram:
    +----------+---------+       
    | ABSTRACT | PUB     |------>
    |   SIM    +---------+       
    | ELEMENT  | PUSH    |------>
    +----------+---------+       
    """

    def __init__(self, name : str, network_config : NetworkConfig, level : int = logging.INFO) -> None:
        """
        Initiates a new simulation element

        ### Args:
            - name (`str`): The element's name
            - network_config (:obj:`NetworkConfig`): description of the addresses pointing to this simulation element
            - level (`int`): logging level for this simulation element
        """
        super().__init__()

        self.name = name
        self._network_config = network_config
        self._my_addresses = []
        self._logger : logging.Logger = self._set_up_logger(level)

        self._clock_config = None
        self._address_ledger = dict()
            
    def _set_up_logger(self, level=logging.DEBUG) -> logging.Logger:
        """
        Sets up a logger for this simulation element

        TODO add save to file capabilities
        """
        logger = logging.getLogger()
        logger.propagate = False
        logger.setLevel(level)

        c_handler = logging.StreamHandler()
        c_handler.setLevel(level)
        logger.addHandler(c_handler)

        return logger 

    def _log(self, msg : str, level=logging.DEBUG) -> None:
        """
        Logs a message to the desired level.
        """
        if level is logging.DEBUG:
            self._logger.debug(f'{self.name}: {msg}')
        elif level is logging.INFO:
            self._logger.info(f'{self.name}: {msg}')
        elif level is logging.WARNING:
            self._logger.warning(f'{self.name}: {msg}')
        elif level is logging.ERROR:
            self._logger.error(f'{self.name}: {msg}')
        elif level is logging.CRITICAL:
            self._logger.critical(f'{self.name}: {msg}')
    
    def run(self) -> None:
        """
        Executes this similation element.
        """
        asyncio.run(self._excetute())

    async def _excetute(self) -> None:
        """
        Main simulation element function. Activates and executes this similation element. 

        Simulation elements perform two element-specific concurrent processes:
            1. _listen(): elements listen to incoming messages
            2. _live(): elements perform a defined set of actions during the simulation
        """
        try:
            # activate and initialize
            self._log('activating...', level=logging.INFO)
            pending = []
            await self._activate()
            self._log('activated!', level=logging.INFO)

            # execute 
            self._log('starting life...', level=logging.INFO)
            listen_task = asyncio.create_task(self._listen())
            listen_task.set_name('listen')

            live_task = asyncio.create_task(self._live())
            live_task.set_name('live')            

            _, pending = await asyncio.wait([listen_task, live_task], return_when=asyncio.FIRST_COMPLETED)

        finally:
            self._log('I am now dead! Terminating all processes...', level=logging.INFO)
            for task in pending:
                task : asyncio.Task
                self._log(f'terminting process `{task.get_name()}`...', level=logging.DEBUG)
                task.cancel()
                await task
                self._log(f'`{task.get_name()}` process terminated.', level=logging.DEBUG)

            # deactivate and clean up
            await self._deactivate()
            self._log('all processes termated successfully. Good night!', level=logging.INFO)

    async def _activate(self) -> None:
        """
        Initiates and executes commands that are thread-sensitive but that must be performed before the simulation starts.
        By default it only initializes network connectivity of the element.

        May be expanded if more capabilities are needed.
        """
        # inititate base network connections 
        self._socket_list = await self._config_network()

    async def _config_network(self) -> list:
        """
        Initializes and connects essential network port sockets for this simulation element. 

        Must be expanded if more connections are needed.
        
        #### Sockets Initialized:
            - _pub_socket (:obj:`Socket`): The entity's broadcast port address
            - _monitor_push_socket (:obj:`Socket`): The simulation's monitor port address

        #### Returns:
            - `list` containing all sockets used by this simulation element
        """
        # initiate ports and connections
        self._context = azmq.Context()

        for address in self._network_config.get_my_addresses():
            if self.__is_address_in_use(address):
                raise Exception(f"{address} address is already in use.")

        # broadcast message publish port
        self._pub_socket = self._context.socket(zmq.PUB)                   
        self._pub_socket.sndhwm = 1100000                                 ## set SNDHWM, so we don't drop messages for slow subscribers
        pub_address : str = self._network_config.get_broadcast_address()
        self._pub_socket.bind(pub_address)
        self._pub_socket_lock = asyncio.Lock()

        # push to monitor port
        self._monitor_push_socket = self._context.socket(zmq.PUSH)
        monitor_address : str = self._network_config.get_monitor_address()
        self._monitor_push_socket.connect(monitor_address)
        self._monitor_push_socket.setsockopt(zmq.LINGER, 0)
        self._monitor_push_socket_lock = asyncio.Lock()

        return [self._pub_socket, self._monitor_push_socket]

    async def _broadcast_message(self, msg : SimulationMessage) -> None:
        """
        Broadcasts a message to all elements subscribed to this element's publish socket
        """
        try:
            self._log(f'acquiring port lock for a message of type {type(msg)}...')
            await self._pub_socket_lock.acquire()
            self._log(f'port lock acquired!')

            self._log(f'sending message of type {type(msg)}...')
            await self._send_from_socket(msg, self._pub_socket, self._pub_socket_lock)
            self._log(f'message transmitted sucessfully!')

        except asyncio.CancelledError:
            self._log(f'message transmission interrupted.')
            
        except Exception as e:
            self._log(f'message transmission failed.')
            raise e

        finally:
            self._pub_socket_lock.release()
            self._log(f'port lock released.')


    async def _push_message_to_monitor(self, msg : SimulationMessage) -> None:
        """
        Pushes a message to the simulation monitor
        """
        try:
            self._log(f'acquiring port lock for a message of type {type(msg)}...')
            await self._monitor_push_socket_lock.acquire()
            self._log(f'port lock acquired!')

            self._log(f'sending message of type {type(msg)}...')
            dst : str = msg.get_dst()
            if dst != SimulationElementTypes.MONITOR.value:
                raise asyncio.CancelledError('attempted to send a non-monitor message to the simulation monitor.')

            await self._send_from_socket(msg, self._monitor_push_socket, self._monitor_push_socket_lock)
            self._log(f'message transmitted sucessfully!')

        except asyncio.CancelledError:
            self._log(f'message transmission interrupted.')
            
        except Exception as e:
            self._log(f'message transmission failed.')
            raise e

        finally:
            self._monitor_push_socket_lock.release()
            self._log(f'port lock released.')

    async def _send_from_socket(self, msg : SimulationMessage, socket : zmq.Socket, socket_lock : asyncio.Lock) -> None:
        """
        Sends a multipart message to a given socket.

        ### Arguments:
            - msg (:obj:`SimulationMessage`): message being sent
            - socket (:obj:`Socket`): socket being used to transmit messages
            - socket_lock (:obj:`asyncio.Lock`): lock restricting access to socket
        """
        try:
            if not socket_lock.locked():
                raise RuntimeError(f'Socket lock for {socket} port must be acquired before sending messages.')

            if socket.socket_type != zmq.REQ and socket.socket_type != zmq.PUB and socket.socket_type != zmq.PUSH:
                raise RuntimeError(f'Cannot send messages from a port of type {socket.socket_type.name}.')

            dst : str = msg.get_dst()
            content : str = str(msg.to_json())
            await socket.send_multipart([dst.encode('ascii'), content.encode('ascii')])

        except asyncio.CancelledError:
            self._log(f'message reception interrupted.')
            return
            
        except Exception as e:
            self._log(f'message reception failed. {e}')
            raise e

    async def _receive_from_socket(self, socket : zmq.Socket, socket_lock : asyncio.Lock) -> list:
        """
        Receives a multipart message from a given socket.

        ### Arguments:
            - socket (:obj:`Socket`): socket being used to receive messages
            - socket_lock (:obj:`asyncio.Lock`): lock restricting access to socket

        ### Returns:
            - dst (`str`) : name of intended destination
            - content (`dict`) : message
        """
        try:
            if not socket_lock.locked():
                raise RuntimeError(f'Socket lock for {socket} port must be acquired before receiving messages.')

            if socket.socket_type != zmq.REQ and socket.socket_type != zmq.REP and socket.socket_type != zmq.SUB:
                raise RuntimeError(f'Cannot receive messages from a port of type {socket.socket_type.name}.')

            dst, content = await socket.recv_multipart()
            dst : str = dst.decode('ascii')
            content : dict = json.loads(content.decode('ascii'))

            return dst, content

        except asyncio.CancelledError:
            self._log(f'message reception interrupted.')
            return None, None
            
        except Exception as e:
            self._log(f'message reception failed.')
            raise e

    def __is_address_in_use(self, address : str) -> bool:
        """
        Checks if an address is already bound to an existing port socket.

        ### Arguments:
            - address (`str`): address being evaluated

        ### Returns:
            - `bool`: True if port is already in use
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            address : str
            _, _, port = address.split(':')
            port = int(port)
            return s.connect_ex(('localhost', port)) == 0

    async def _deactivate(self) -> None:
        """
        Shut down procedure for this simulation entity. 
        Must close all socket connections.
        """
        # close connections
        self._close_sockets()

        # close network context
        if self._context is not None:
            self._context.term()

    def _close_sockets(self) -> None:
        """
        Closes all sockets present in the abstract class Entity
        """
        for socket in self._socket_list:
            socket : zmq.Socket
            socket.close()

    async def _sim_wait(self, delay : float) -> None:
        """
        Waits for a given delay to occur according to the clock configuration being used

        ### Arguments:
            - delay (`float`): number of seconds to be waited
        """
        try:
            async def cancellable_wait(delay : float, sim_clock_freq : float = 1.0):
                try:
                    await asyncio.sleep(delay / sim_clock_freq)
                except asyncio.CancelledError:
                    self._log(f'Cancelled sleep of delay {delay / sim_clock_freq} [s]')
                    raise

            wait_for_clock = None

            if isinstance(self._clock_config, RealTimeClockConfig):
                self._clock_config : RealTimeClockConfig
                wait_for_clock = asyncio.create_task(cancellable_wait(delay))
                await wait_for_clock

            elif isinstance(self._clock_config, AcceleratedRealTimeClockConfig):
                self._clock_config : AcceleratedRealTimeClockConfig
                wait_for_clock = asyncio.create_task(cancellable_wait(delay, self._clock_config._sim_clock_freq))
                await wait_for_clock

            else:
                raise NotImplementedError(f"Clock config of type {type(self._clock_config)} not yet implemented.")
        
        except asyncio.CancelledError:
            if wait_for_clock is not None:
                wait_for_clock : asyncio.Task
                wait_for_clock.cancel()
                await wait_for_clock

        except Exception as e:
            raise e

    @abstractmethod
    async def _live(self) -> None:
        """
        Procedure to be executed by the simulation element during the simulation. 

        Element will deactivate if this method returns.

        Procedure must include a handler for asyncio.CancelledError exceptions.
        """
        pass    
    
    @abstractmethod
    async def _listen(self) -> None:
        """
        Procedure for listening for incoming messages from other elements during the simulation.

        Element will deactivate if this method returns.

        Procedure must include a handler for asyncio.CancelledError exceptions.
        """
        pass