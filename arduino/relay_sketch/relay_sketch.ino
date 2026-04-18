/*
 * Sketch Arduino para controle de relé via serial.
 *
 * Protocolo:
 *   Recebe '1' → ativa relé (HIGH no pino)
 *   Recebe '0' → desativa relé (LOW no pino)
 *
 * O nó ROS2 relay_controller envia '1', espera 1s, e envia '0'.
 * O Arduino só obedece — a temporização fica no lado do PC.
 *
 * Conexão:
 *   RELAY_PIN → módulo relé (IN)
 *   GND       → módulo relé (GND)
 *   5V        → módulo relé (VCC)
 *
 * Ajuste RELAY_PIN conforme seu hardware.
 */

#define RELAY_PIN 7
#define BAUD_RATE 9600

void setup() {
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);  // relé desligado no boot
  Serial.begin(BAUD_RATE);
}

void loop() {
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd == '1') {
      digitalWrite(RELAY_PIN, HIGH);
    } else if (cmd == '0') {
      digitalWrite(RELAY_PIN, LOW);
    }
  }
}
