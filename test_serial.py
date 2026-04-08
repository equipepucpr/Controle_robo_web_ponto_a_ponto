"""
Teste direto da serial do hoverboard — SEM ROS2.
Envia o mesmo protocolo que o driver C++ envia.
Confirma se o hoverboard responde ao protocolo serial.

Uso:
    python3 test_serial.py
"""
import struct
import time
import sys

PORT     = "/dev/ttyUSB0"
BAUD     = 115200
START_FRAME = 0xABCD

def make_command(speed: int, steer: int) -> bytes:
    """Monta o pacote SerialCommand igual ao driver C++."""
    checksum = (START_FRAME ^ (steer & 0xFFFF) ^ (speed & 0xFFFF)) & 0xFFFF
    # < = little-endian, H=uint16, h=int16
    return struct.pack('<HhhH', START_FRAME, steer, speed, checksum)

def main():
    try:
        import serial
    except ImportError:
        print("Instale pyserial:  pip install pyserial")
        sys.exit(1)

    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
        print(f"Porta {PORT} aberta a {BAUD} baud")
    except Exception as e:
        print(f"Erro ao abrir {PORT}: {e}")
        sys.exit(1)

    print()
    print("Enviando speed=0, steer=0 por 2s (deve estar parado)...")
    t_end = time.time() + 2.0
    while time.time() < t_end:
        ser.write(make_command(0, 0))
        time.sleep(0.02)   # 50 Hz, igual ao driver

    print("Enviando speed=300, steer=0 por 3s (deve ir para frente)...")
    print(">>> SEGURE O ROBÔ ou coloque no ar antes de continuar <<<")
    input("Pressione Enter quando estiver pronto...")
    t_end = time.time() + 3.0
    while time.time() < t_end:
        ser.write(make_command(300, 0))
        time.sleep(0.02)
        # Tenta ler feedback para confirmar que o hoverboard responde
        data = ser.read(ser.in_waiting or 1)
        if data:
            print(f"  Feedback recebido: {data.hex()}")

    print("Parando...")
    for _ in range(10):
        ser.write(make_command(0, 0))
        time.sleep(0.02)

    ser.close()
    print("Feito.")

if __name__ == '__main__':
    main()
