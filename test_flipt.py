#!/usr/bin/env python3
"""
Script de prueba para verificar la conexión con Flipt en Railway
"""

import os
import sys
from dotenv import load_dotenv
import flipt
import requests

# Cargar variables de entorno
load_dotenv()

FLIPT_URL = os.getenv('FLIPT_URL', 'https://flipt-production-ff4a.up.railway.app')
FLIPT_NAMESPACE = os.getenv('FLIPT_NAMESPACE', 'default')
FLIPT_FLAG_KEY = os.getenv('FLIPT_FLAG_KEY', 'mia')

print("=" * 60)
print("🧪 PRUEBA DE CONEXIÓN CON FLIPT")
print("=" * 60)
print()

# Test 1: Health Check
print("📡 Test 1: Verificando conectividad con Flipt...")
try:
    response = requests.get(f"{FLIPT_URL}/health", timeout=10)
    if response.status_code == 200:
        print("   ✅ Flipt está accesible")
        print(f"   Estado: {response.json()}")
    else:
        print(f"   ❌ Error: Status code {response.status_code}")
        sys.exit(1)
except Exception as e:
    print(f"   ❌ Error de conexión: {e}")
    print(f"   URL intentada: {FLIPT_URL}/health")
    sys.exit(1)

print()

# Test 2: Verificar que el flag existe
print(f"🚩 Test 2: Verificando flag '{FLIPT_FLAG_KEY}'...")
try:
    response = requests.get(
        f"{FLIPT_URL}/api/v1/namespaces/{FLIPT_NAMESPACE}/flags/{FLIPT_FLAG_KEY}",
        timeout=10
    )
    if response.status_code == 200:
        flag_data = response.json()
        print(f"   ✅ Flag encontrado")
        print(f"   Nombre: {flag_data.get('name', 'N/A')}")
        print(f"   Tipo: {flag_data.get('type', 'N/A')}")
        print(f"   Habilitado: {flag_data.get('enabled', 'N/A')}")
    elif response.status_code == 404:
        print(f"   ❌ Flag '{FLIPT_FLAG_KEY}' no existe")
        print(f"   Crea el flag en: {FLIPT_URL}/#/namespaces/{FLIPT_NAMESPACE}/flags")
        sys.exit(1)
    else:
        print(f"   ⚠️  Respuesta inesperada: {response.status_code}")
        print(f"   {response.text}")
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

print()

# Test 3: Evaluar el flag
print("🎯 Test 3: Evaluando el flag...")
try:
    flipt_client = flipt.FliptClient(url=FLIPT_URL)
    
    # Evaluar para un usuario de prueba
    test_user_id = "test_user_123"
    result = flipt_client.evaluation.boolean(
        namespace_key=FLIPT_NAMESPACE,
        flag_key=FLIPT_FLAG_KEY,
        entity_id=test_user_id,
        context={"user_id": test_user_id}
    )
    
    print(f"   ✅ Evaluación exitosa")
    print(f"   Usuario de prueba: {test_user_id}")
    print(f"   Resultado: {'🟢 HABILITADO' if result.enabled else '🔴 DESHABILITADO'}")
    print(f"   Razón: {result.reason}")
    
except Exception as e:
    print(f"   ❌ Error al evaluar: {e}")
    sys.exit(1)

print()
print("=" * 60)
print("✨ TODAS LAS PRUEBAS PASARON")
print("=" * 60)
print()
print("🎉 Tu bot está listo para conectarse con Flipt!")
print()
print("📋 Configuración actual:")
print(f"   FLIPT_URL: {FLIPT_URL}")
print(f"   FLIPT_NAMESPACE: {FLIPT_NAMESPACE}")
print(f"   FLIPT_FLAG_KEY: {FLIPT_FLAG_KEY}")
print()
print("🚀 Ahora puedes iniciar el bot con: python discord_bot.py")
print(f"🎛️  Panel de Flipt: {FLIPT_URL}/#/namespaces/{FLIPT_NAMESPACE}/flags/{FLIPT_FLAG_KEY}")

