import logging
import unittest
from tqdm import tqdm

import zmq
from dmas.element import *
from dmas.messages import *

from dmas.modules import InternalModule
from dmas.network import NetworkConfig


class TestInternalModule(unittest.TestCase): 
    class DummyModule(InternalModule):
        async def _listen(self):
            return
        
        async def _routine(self):
            return

    class TestModule(InternalModule):
        def __init__(self, 
                    parent_name : str, 
                    module_name: str, 
                    node_rep_port : int, 
                    node_pub_port : int, 
                    level: int = logging.INFO, 
                    logger: logging.Logger = None
                    ) -> None:
            internal_address_map = {
                                    zmq.REQ: [f'tcp://localhost:{node_rep_port}'],
                                    zmq.SUB: [f'tcp://localhost:{node_pub_port}']
                                    }
            network_config = NetworkConfig(parent_name, internal_address_map, dict())
            super().__init__(module_name, network_config, [], level, logger)

        async def _listen(self):
            try:
                self._log(f'waiting for parent module to deactivate me...')
                while True:
                    dst, src, content = await self._receive_internal_msg(zmq.SUB)

                    if (dst not in self.name 
                        or self.get_parent_name() not in src 
                        or content['msg_type'] != NodeMessageTypes.MODULE_DEACTIVATE.value):
                        self._log('wrong message received. ignoring message...')
                    else:
                        self._log('deactivate module message received! ending simulation...')
                        break

            except asyncio.CancelledError:
                self._log(f'`_listen()` interrupted. {e}')
                return
            except Exception as e:
                self._log(f'`_listen()` failed. {e}')
                raise e
            
        async def _routine(self):
            try:
                # do some 'work'
                while True:
                    await asyncio.sleep(1e6)
                   
            except asyncio.CancelledError:
                self._log(f'`_routine()` interrupted. {e}')
                return
            except Exception as e:
                self._log(f'`_routine()` failed. {e}')
                raise e

    class DummyNode(SimulationElement):
        def __init__(self, 
                    element_name: str, 
                    n_modules : int, 
                    port : int,
                    level: int = logging.INFO, 
                    logger: logging.Logger = None
                    ) -> None:

            internal_address_map = {zmq.REP : [f'tcp://*:{port}'],
                                    zmq.PUB : [f'tcp://*:{port+1}']}

            network_config = NetworkConfig('TEST_NETWORK', internal_address_map=internal_address_map, external_address_map=dict())

            super().__init__(element_name, network_config, level, logger)

            self.__modules = []
            for i in range(n_modules):
                self.__modules.append(TestInternalModule.TestModule(element_name, 
                                                                    f'MODULE_{i}', 
                                                                    port, 
                                                                    port+1, 
                                                                    level,
                                                                    self.get_logger()))

        def run(self) -> int:
            """
            Main function. Executes this similation element along with its submodules.

            Returns `1` if excecuted successfully or if `0` otherwise
            """
            try:
                with concurrent.futures.ThreadPoolExecutor(len(self.__modules) + 1) as pool:
                    pool.submit(asyncio.run, *[self._run_routine()])
                    for module in self.__modules:
                        module : InternalModule
                        pool.submit(module.run, *[])

            except Exception as e:
                self._log(f'`run()` interrupted. {e}')
                raise e

        async def _external_sync(self):
            year = 2023
            month = 1
            day = 1
            hh = 12
            mm = 00
            ss = 00
            start_date = datetime(year, month, day, hh, mm, ss)
            end_date = datetime(year, month, day, hh, mm, ss+1)

            return RealTimeClockConfig(str(start_date), str(end_date)), dict()
        
        async def _internal_sync(self, clock_config : ClockConfig) -> dict:
            try:
                # wait for module sync request       
                await self.__wait_for_module_sycs()

                # create internal ledger
                internal_address_ledger = dict()
                for module in self.__modules:
                    module : InternalModule
                    internal_address_ledger[module.name] = module.get_network_config()
                
                # broadcast simulation info to modules
                msg = NodeInfoMessage(self._element_name, self._element_name, clock_config.to_dict())
                await self._send_internal_msg(msg, zmq.PUB)

                # return ledger
                return internal_address_ledger
            
            except asyncio.CancelledError:
                return
            
        async def __wait_for_module_sycs(self):
            """
            Waits for all internal modules to send their respective sync requests
            """
            await self.__wait_for_module_messages(ModuleMessageTypes.SYNC_REQUEST, 'Syncing w/ Internal Nodes')

        async def __wait_for_module_messages(self, target_type : ModuleMessageTypes, desc : str):
            """
            Waits for all internal modules to send a message of type `target_type` through the node's REP port
            """
            responses = []
            module_names = [f'{self._element_name}/{m._element_name}' for m in self.__modules]

            with tqdm(total=len(self.__modules) , desc=f'{self.name}: {desc}') as pbar:
                while len(responses) < len(self.__modules):
                    # listen for messages from internal module
                    dst, src, msg_dict = await self._receive_internal_msg(zmq.REP)
                    dst : str; src : str; msg_dict : dict
                    msg_type = msg_dict.get('msg_type', None)

                    if (dst in self.name
                        and src in module_names
                        and msg_type == target_type.value
                        and src not in responses
                        ):
                        # Add to list of registered modules if it hasn't been registered before
                        responses.append(src)
                        pbar.update(1)
                        resp = NodeReceptionAckMessage(self._element_name, src)
                    else:
                        print(dst in self.name, dst, self.name)
                        print(src in module_names, src, module_names)
                        print(msg_type == target_type.value, msg_type, target_type.value)
                        print(src not in responses, src, responses)
                        # ignore message
                        resp = NodeReceptionIgnoredMessage(self._element_name, src)

                    # respond to module
                    await self._send_internal_msg(resp, zmq.REP)

        async def _execute(self):
            dt = self._clock_config.get_total_seconds()
            
            for _ in tqdm (range (10), desc=f'{self.name} Working'):
                await asyncio.sleep(dt/10)

            # node is disabled. inform modules that the node is terminating
            self._log('node\'s `live()` finalized. Terminating internal modules....')
            terminate_msg = TerminateInternalModuleMessage(self._element_name, self._element_name)
            await self._send_internal_msg(terminate_msg, zmq.PUB)

            # wait for all modules to terminate and become offline
            terminate_task = asyncio.create_task(self.__wait_for_offline_modules())
            await terminate_task

        async def __wait_for_offline_modules(self) -> None:
            """
            Waits for all internal modules to become offline
            """
            # send terminate message to all modules
            responses = []
            module_names = [m.name for m in self.__modules]

            with tqdm(total=len(self.__modules) , desc=f'{self.name} Offline Internal Modules') as pbar:
                while len(responses) < len(self.__modules):
                    # listen for messages from internal nodes
                    dst, src, msg_dict = await self._receive_internal_msg(zmq.REP)
                    dst : str; src : str; msg_dict : dict
                    msg_type = msg_dict.get('msg_type', None)    

                    if (
                        dst not in self.name
                        or src not in module_names 
                        or msg_type != ModuleMessageTypes.MODULE_DEACTIVATED.value
                        or src in responses
                        ):
                        # undesired message received. Ignoring and trying again later
                        print(dst not in self.name)
                        print(src not in module_names )
                        print(msg_type != ModuleMessageTypes.MODULE_DEACTIVATED.value)
                        print(src in responses)

                        self._log(f'received undesired message of type {msg_type}, expected tye {ModuleMessageTypes.MODULE_DEACTIVATED.value}. Ignoring...')
                        resp = NodeReceptionIgnoredMessage(self._element_name, src)

                    else:
                        # add to list of offline modules if it hasn't been registered as offline before
                        pbar.update(1)
                        resp = NodeReceptionAckMessage(self._element_name, src)
                        responses.append(src)
                        self._log(f'{src} is now offline! offline module status: {len(responses)}/{len(self.__modules)}')

                    await self._send_internal_msg(resp, zmq.REP)
        
        async def _publish_deactivate(self):
            return

        async def _wait_sim_start(self):
            # wait for all modules to become online
            await self.__wait_for_ready_modules()

            self._log('all external nodes are now online! Informing internal modules of simulation information...')
            sim_start = ActivateInternalModuleMessage(self._element_name, self._element_name)
            await self._send_internal_msg(sim_start, zmq.PUB)

        async def __wait_for_ready_modules(self) -> None:
            """
            Waits for all internal modules to become online and be ready to start their simulation
            """
            await self.__wait_for_module_messages(ModuleMessageTypes.MODULE_READY, 'Online Internal Modules')

    
    def test_init(self):
        port = 5555
        n_modules = 1

        module = TestInternalModule.TestModule('TEST_NODE', 'MODULE_0', port, port+1)
        self.assertTrue(isinstance(module, TestInternalModule.TestModule))

        node = TestInternalModule.DummyNode('NODE_0', n_modules, port, logger=module.get_logger())
        self.assertTrue(isinstance(node, TestInternalModule.DummyNode))

        with self.assertRaises(AttributeError):
            network_config = NetworkConfig('TEST', {}, {})
            TestInternalModule.DummyModule('TEST', network_config, logger=module.get_logger())
            
            network_config = NetworkConfig('TEST', {zmq.REQ: [f'tcp://localhost:{port+2}']}, {})
            TestInternalModule.DummyModule('TEST', network_config, logger=module.get_logger())

            network_config = NetworkConfig('TEST', {}, {zmq.SUB: [f'tcp://localhost:{port+3}']})
            TestInternalModule.DummyModule('TEST', network_config, logger=module.get_logger())

    def test_module(self):
        port = 5555
        n_modules = 100
        level = logging.WARNING

        node = TestInternalModule.DummyNode('NODE_0', n_modules, port, level=level)
        node.run()