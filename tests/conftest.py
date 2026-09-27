import pytest

from ultron.memory import Memory
from ultron.ollama import Ollama

from .fake_ollama import FakeOllama


@pytest.fixture
def ollama():
    fake = FakeOllama()
    yield fake
    fake.close()


@pytest.fixture
def client(ollama):
    return Ollama(ollama.url, timeout=10)


@pytest.fixture
def memory(tmp_path):
    return Memory(tmp_path / "memory.json")
