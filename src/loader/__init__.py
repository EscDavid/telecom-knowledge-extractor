"""Fase DB — Loader del catalogo TKC a MySQL (ispm_tkc).

Fase 1 (lectura): hashing (deteccion de cambios) + readiness (4 tiers) + CLI `status`.
No importa PyMySQL aqui: hashing/readiness son stdlib puro y testeables sin BD.
"""
