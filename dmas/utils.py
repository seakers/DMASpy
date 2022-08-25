from abc import abstractclassmethod
import asyncio
from enum import Enum, IntEnum
import random
import numpy

class SpacecraftModules(Enum):
    ENGINEERING_MODULE = 'ENGINEERING_MODULE'
    SCIENCE_MODULE = 'SCIENCE_MODULE'
    SCHEDULING_MODULE = 'SCHEDULING_MODULE'

class SimClocks(Enum):
    # asynchronized clocks
    # -Each node in the network carries their own clocks to base their waits with
    REAL_TIME = 'REAL_TIME'             # runs simulations in real-time. 
    REAL_TIME_FAST = 'REAL_TIME_FAST'   # runs simulations in spead up real-time. Each real time second represents a user-given amount of simulation seconds

    # synchronized clocks
    # -Each node requests to be notified by the server when a particular time is reached, which they use to base their waits
    SERVER_TIME = 'SERVER_TIC'          # server sends tics at a fixed rate in real-time
    SERVER_TIME_FAST = 'SERVER_TIC'     # server sends tics at a fixed rate in spead up real-time
    SERVER_STEP = 'SERVER_STEP'         # server waits until all agents have submitted a tic request and fast-forwards to that time

class Container:
    def __init__(self, level: float =0, capacity: float =numpy.Infinity):
        if level > capacity:
            raise Exception('Initial level must be lower than maximum capacity.')

        self.level = level
        self.capacity = capacity
        self.updated = None

        self.updated = asyncio.Event()
        self.lock = asyncio.Lock()

    async def set_level(self, value):
        self.level = 0
        await self.put(value)

    async def empty(self):
        self.set_level(0)

    async def put(self, value):
        if self.updated is None:
            raise Exception('Container not activated in event loop')

        def accept():
            return self.level + value <= self.capacity
        
        await self.lock.acquire()
        while not accept():
            self.lock.release()
            self.updated.clear()
            await self.updated.wait()
            await self.lock.acquire()        
        self.level += value
        self.updated.set()
        self.lock.release()

    async def get(self, value):
        if self.updated is None:
            raise Exception('Container not activated in event loop')

        def accept():
            return self.level - value >= 0
        
        await self.lock.acquire()
        while not accept():
            self.lock.release()
            self.updated.clear()
            await self.updated.wait()
            await self.lock.acquire()        
        self.level -= value
        self.updated.set()
        self.lock.release()

    async def when_cond(self, cond):
        if self.updated is None:
            raise Exception('Container not activated in event loop')
             
        while not cond():
            self.updated.clear()
            await self.updated.wait()
        return True

    async def when_not_empty(self):
        def accept():
            return self.level > 0
        
        await self.when_cond(accept)
    
    async def when_empty(self):
        def accept():
            return self.level == 0
        
        await self.when_cond(accept)

    async def when_less_than(self, val):
        def accept():
            return self.level < val
        
        await self.when_cond(accept)
    
    async def when_leq_than(self, val):
        def accept():
            return self.level <= val
        
        await self.when_cond(accept)

    async def when_greater_than(self, val):
        def accept():
            return self.level > val
        
        await self.when_cond(accept)
    
    async def when_geq_than(self, val):
        def accept():
            return self.level >= val
        
        await self.when_cond(accept)

async def f1(container: Container):
    print('tast1 starting...')    
    await asyncio.sleep(1)
    await container.put(1)
    
async def f2(container: Container):
    print('tast2 starting...')
    # await asyncio.sleep(0.5)
    print(f'current container level: {container.level}')
    # await container.when_greater_than(0)
    
    await container.get(1)
    print(f'current container level: {container.level}')

async def f3(container: Container):
    for _ in range(100):
        await container.put(1)
        await asyncio.sleep(random.random()/10)
        await container.get(1)

async def main():
    container = Container(0, 100)

    # t1 = asyncio.create_task(f1(container))
    # t2 = asyncio.create_task(f2(container))
    t1 = asyncio.create_task(f3(container))
    t2 = asyncio.create_task(f3(container))
    
    print(f'Initial container level: {container.level}')
    await asyncio.wait([t1, t2], return_when=asyncio.ALL_COMPLETED)
    print(f'Final container level: {container.level}')

if __name__ == '__main__':
    asyncio.run(main())