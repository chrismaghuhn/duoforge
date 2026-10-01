"""Self-play learning over the DuoForge batch runtime (decision 0014): JAX, optax, NumPy.

JAX takes GPU memory as it needs it here, not 75 percent up front: the GPU
also drives the desktop.
"""
import os

os.environ.setdefault("XLA_PYTHON_CLIENT_PREALLOCATE", "false")
