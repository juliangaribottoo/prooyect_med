"""
Script de una sola ejecución: crea el usuario manual julian@gmail.com / prueba123
"""
from database import init_db, crear_usuario
from auth import hash_password

if __name__ == "__main__":
    init_db()
    pw_hash = hash_password("prueba123")
    if crear_usuario("julian@gmail.com", pw_hash, "asesor"):
        print("Usuario julian@gmail.com creado correctamente.")
    else:
        print("El usuario ya existía o hubo un error (email duplicado).")
