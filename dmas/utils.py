import asyncio
from typing import Union
import numpy

"""
------------------
ASYNCHRONOUS CONTAINER
------------------
"""
class Container:
    """
    ## Container Object

    Holds a numerical value ('float' or 'int'). 
    Offers asynchronous events when the value is modified
    """
    def __init__(self, level : Union[float, int] = 0, capacity : Union[float, int] = numpy.Infinity):
        if level > capacity:
            raise Exception('Initial level must be lower than maximum capacity.')

        self.level = level
        self.capacity = capacity

        self.updated = asyncio.Event()
        self.lock = asyncio.Lock()

    async def set_level(self, value : Union[float, int]) -> None:
        self.level = 0
        await self.put(value)

    async def empty(self) -> None:
        self.set_level(0)

    async def put(self, value : Union[float, int]) -> None:
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

    async def get(self, value : Union[float, int]):
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

        return value

    async def __when_cond(self, cond : callable) -> bool:
        if self.updated is None:
            raise Exception('Container not activated in event loop')
             
        while not cond():
            self.updated.clear()
            await self.updated.wait()
        return True

    async def when_not_empty(self) -> None:
        def accept():
            return self.level > 0
        
        await self.__when_cond(accept)
    
    async def when_empty(self) -> None:
        def accept():
            return self.level == 0
        
        await self.__when_cond(accept)

    async def when_less_than(self, value : Union[float, int]) -> None:
        def accept():
            return self.level < value
        
        await self.__when_cond(accept)
    
    async def when_leq_than(self, value : Union[float, int]) -> None:
        def accept():
            return self.level <= value
        
        await self.__when_cond(accept)

    async def when_greater_than(self, value : Union[float, int]) -> None:
        def accept():
            return self.level > value
        
        await self.__when_cond(accept)
    
    async def when_geq_than(self, value : Union[float, int]) -> None:
        def accept():
            return self.level >= value
        
        await self.__when_cond(accept)