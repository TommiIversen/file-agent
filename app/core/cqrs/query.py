from abc import ABC, abstractmethod
from typing import Generic, TypeVar

# Definerer generiske typer for at sikre stærk type-checking
# TQuery kan være enhver subklasse af Query
# TResult kan være enhver returtype
TQuery = TypeVar('TQuery', bound='Query')
TResult = TypeVar('TResult')


class Query(ABC):
    """
    Baseklasse for alle Query-objekter.
    En Query er en DTO (Data Transfer Object), der repræsenterer en
    forespørgsel om data. Den ændrer ikke systemets tilstand.
    """
    pass


class QueryHandler(Generic[TQuery, TResult], ABC):
    """
    Base-interface for alle Query Handlers.
    Sikrer, at hver handler har en 'handle'-metode.
    """
    @abstractmethod
    async def handle(self, query: TQuery) -> TResult:
        """Håndterer den givne query og returnerer et resultat."""
        raise NotImplementedError