import logging
from dmas.nodes import Node
from dmas.utils import *
from dmas.network import *

class EnvironmentNode(Node):
    def __init__(self, port, logger: logging.Logger) -> None:
        network_config = NetworkConfig( 'TEST_NETWORK', 
                                        internal_address_map={},
                                        external_address_map={  zmq.REQ:  [f'tcp://localhost:{port}'],
                                                                zmq.SUB:  [f'tcp://localhost:{port+1}'],
                                                                zmq.PUSH: [f'tcp://localhost:{port+2}'],
                                                                zmq.REP:  [f'tcp://*:{port+3}'],
                                                                }
                                        )        

        super().__init__(SimulationElementRoles.ENVIRONMENT.name, network_config, [], logger=logger)

    async def live(self):
        try:
            while True:
                self.log('waiting on messages...', level=logging.INFO)

                _, src, msg_dict = await self._receive_external_msg(zmq.REP)
                src : str; msg_dict : dict  

                self.log(f'Message from {src}: {msg_dict}', level=logging.INFO)

                resp = NodeReceptionAckMessage(self.name, src)
                await self._send_external_msg(resp, zmq.REP)

        except asyncio.CancelledError:
            return