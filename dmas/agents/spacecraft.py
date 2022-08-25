import asyncio
import json
import logging
from agents.agent import AgentNode
from components import Battery, OnBoardComputer, SolarPanel, Transceiver
from messages import BroadcastTypes
from modules.engineering import EngineeringModule
from utils import SimClocks

"""
 ____                                                             ___  __      
/\  _`\                                                         /'___\/\ \__   
\ \,\L\_\  _____      __      ___     __    ___   _ __    __   /\ \__/\ \ ,_\  
 \/_\__ \ /\ '__`\  /'__`\   /'___\ /'__`\ /'___\/\`'__\/'__`\ \ \ ,__\\ \ \/  
   /\ \L\ \ \ \L\ \/\ \L\.\_/\ \__//\  __//\ \__/\ \ \//\ \L\.\_\ \ \_/ \ \ \_ 
   \ `\____\ \ ,__/\ \__/.\_\ \____\ \____\ \____\\ \_\\ \__/.\_\\ \_\   \ \__\
    \/_____/\ \ \/  \/__/\/_/\/____/\/____/\/____/ \/_/ \/__/\/_/ \/_/    \/__/
             \ \_\                                                             
              \/_/                                                             
 ______                         __        __  __              __               
/\  _  \                       /\ \__    /\ \/\ \            /\ \              
\ \ \L\ \     __      __    ___\ \ ,_\   \ \ `\\ \    ___    \_\ \     __      
 \ \  __ \  /'_ `\  /'__`\/' _ `\ \ \/    \ \ , ` \  / __`\  /'_` \  /'__`\    
  \ \ \/\ \/\ \L\ \/\  __//\ \/\ \ \ \_    \ \ \`\ \/\ \L\ \/\ \L\ \/\  __/    
   \ \_\ \_\ \____ \ \____\ \_\ \_\ \__\    \ \_\ \_\ \____/\ \___,_\ \____\   
    \/_/\/_/\/___L\ \/____/\/_/\/_/\/__/     \/_/\/_/\/___/  \/__,_ /\/____/   
              /\____/                                                          
              \_/__/                                                         
"""

class SpacecraftAgentNode(AgentNode):
    

    def __init__(self, name, scenario_dir, component_list) -> None:
        super().__init__(name, scenario_dir)
        self.modules = [EngineeringModule(self, component_list)]

    async def broadcast_reception_handler(self):
        """
        Listens for broadcasts from the environment. Stops processes when simulation end-command is received.
        """
        try:
            while True:
                msg_string = await self.environment_broadcast_socket.recv_json()
                msg_dict = json.loads(msg_string)

                src = msg_dict['src']
                dst = msg_dict['dst']
                msg_type = msg_dict['@type']
                t_server = msg_dict['server_clock']

                self.message_logger.info(f'Received message of type {msg_type} from {src} intended for {dst} with server time of t={t_server}!')
                self.log(f'Received message of type {msg_type} from {src} intended for {dst} with server time of t={t_server}!')

                if self.name == dst or 'all' == dst:
                    msg_type = BroadcastTypes[msg_type]
                    if msg_type is BroadcastTypes.SIM_END_EVENT:
                        self.log('Simulation end broadcast received! Terminating agent...', level=logging.INFO)
                        return

                    elif msg_type is BroadcastTypes.TIC_EVENT:
                        if (self.CLOCK_TYPE == SimClocks.SERVER_STEP 
                            or self.CLOCK_TYPE == SimClocks.SERVER_TIME
                            or self.CLOCK_TYPE == SimClocks.SERVER_TIME_FAST):
                            
                            # use server clock broadcasts to update internal clock
                            self.message_logger.info(f'Updating internal clock.')
                            await self.sim_time.set_level(t_server)
                            self.log('Updated internal clock.')
                    else:
                        self.log(f'Broadcasts of type {msg_type.name} not yet supported.')
                else:
                    self.log('Broadcast not intended for this agent. Discarding message...')
        except asyncio.CancelledError:
            return

"""
--------------------
MAIN
--------------------    
"""
if __name__ == '__main__':
    print('Initializing spacecraft agent...')
    scenario_dir = './scenarios/sim_test'

    ob_comp = OnBoardComputer(1, 100)
    transceiver = Transceiver(1, 100, 10)
    solar_panel = SolarPanel(10)
    battery = Battery(10, 100)

    component_list = [ob_comp, transceiver, solar_panel, battery]

    agent = SpacecraftAgentNode('Mars1', scenario_dir, component_list)
    
    asyncio.run(agent.live())