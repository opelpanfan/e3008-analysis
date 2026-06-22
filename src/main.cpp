#include <Arduino.h>
#include <driver/twai.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

#ifndef CAN_RX_PIN
#define CAN_RX_PIN 4
#endif

#ifndef CAN_TX_PIN
#define CAN_TX_PIN 5
#endif

#ifndef CAN_STBY_PIN
#define CAN_STBY_PIN -1
#endif

#ifndef CAN_BITRATE
#define CAN_BITRATE 500000
#endif

// Key IDs from findings
static constexpr uint32_t ID_154 = 0x154;  // torque/request related
static constexpr uint32_t ID_281 = 0x281;  // contactor command progression
static constexpr uint32_t ID_334 = 0x334;  // cell voltages mux
static constexpr uint32_t ID_353 = 0x353;  // mode/SOC related
static constexpr uint32_t ID_3F4 = 0x3F4;  // temperature mux
static constexpr uint32_t ID_428 = 0x428;  // watchdog-like counter
static constexpr uint32_t ID_583 = 0x583;  // validity/count-related
static constexpr uint32_t ID_591 = 0x591;  // contactor state feedback

static constexpr uint16_t MAX_CELLS = 128;
static constexpr uint16_t MAX_TEMPS = 64;
static constexpr size_t LINE_BUF_SZ = 160;
static constexpr uint32_t KP_281_INTERVAL_MS = 135; // 0x281 hold rate: ~7.4 Hz observed
static constexpr uint32_t KP_428_INTERVAL_MS = 58;  // 0x428 watchdog rate: ~17 Hz observed

struct Telemetry {
  uint16_t cellmV[MAX_CELLS] = {0};
  bool cellValid[MAX_CELLS] = {false};
  int16_t tempC[MAX_TEMPS] = {0};
  bool tempValid[MAX_TEMPS] = {false};

  uint8_t battRaw0 = 0;
  uint8_t battRaw1 = 0;
  uint8_t socByte = 0;
  bool socValid = false;

  uint8_t watchdog428 = 0;
  bool watchdogValid = false;

  uint8_t torqueRawLo = 0;
  uint8_t torqueRawHi = 0;
  bool torqueValid = false;

  uint8_t state591[8] = {0};
  bool state591Valid = false;
  uint32_t last591ChangeMs = 0;
  uint32_t lastRxMs = 0;

  uint32_t rxFrames = 0;
  uint32_t rxInteresting = 0;
};

struct SequenceRunner {
  bool active = false;
  char name[24] = {0};

  uint8_t values[12] = {0};
  uint32_t delaysMs[12] = {0};
  uint8_t len = 0;
  uint8_t index = 0;
  uint32_t nextStepAt = 0;

  uint8_t ctx[4] = {0};
};

static Telemetry g_t;
static SequenceRunner g_seq;

static bool g_rawPrint = false;
static bool g_streamTelemetry = true;
static uint32_t g_lastPeriodicStatus = 0;

// ── Keepalive / hold-closed state ─────────────────────────────────────────
// After close, VCU must keep sending 0x281 (~135 ms, rolling byte0 -0x0F) and
// 0x428 watchdog (~58 ms, rolling byte0 -0x0F) or BMS will open contactors.
static bool     g_kp281 = false;
static uint8_t  g_kp281B0 = 0xDB;            // initial byte0 right after close
static uint32_t g_kp281NextMs = 0;
static const uint8_t KP_281_HOLD_CTX[4] = {0x67, 0x0D, 0x80, 0x00}; // dominant hold ctx

static bool     g_kp428 = false;
static uint8_t  g_kp428B0 = 0xC2;            // initial rolling byte0
static uint32_t g_kp428NextMs = 0;

static char g_lineBuf[LINE_BUF_SZ];
static size_t g_lineLen = 0;

static bool isHexChar(char c) {
  return isxdigit(static_cast<unsigned char>(c)) != 0;
}

static void bytesToHex(const uint8_t *data, uint8_t len, char *out, size_t outSz) {
  if (outSz == 0) return;
  size_t pos = 0;
  for (uint8_t i = 0; i < len; i++) {
    if (pos + 2 >= outSz) break;
    int n = snprintf(out + pos, outSz - pos, "%02X", data[i]);
    if (n <= 0) break;
    pos += static_cast<size_t>(n);
  }
  out[pos] = '\0';
}

static void printFrame(const twai_message_t &msg) {
  char hex[32];
  bytesToHex(msg.data, msg.data_length_code, hex, sizeof(hex));
  Serial.printf("[RX] ID=0x%03lX DLC=%u DATA=%s\n", msg.identifier, msg.data_length_code, hex);
}

static const char *state591Name(const uint8_t s[8]) {
  // Known state signatures from findings (partial mapping)
  static const uint8_t OFF_STABLE[8] = {0x00, 0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00};
  static const uint8_t WAKE[8] = {0x28, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
  static const uint8_t PRECHARGE[8] = {0x08, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00};
  static const uint8_t MAIN_CLOSED[8] = {0x00, 0x00, 0x00, 0x00, 0x04, 0x10, 0x00, 0x00};
  static const uint8_t OPEN_BEGIN[8] = {0x08, 0x00, 0x00, 0x00, 0x10, 0x08, 0x00, 0x00};

  if (memcmp(s, OFF_STABLE, 8) == 0) return "OFF_STABLE";
  if (memcmp(s, WAKE, 8) == 0) return "WAKE";
  if (memcmp(s, PRECHARGE, 8) == 0) return "PRECHARGE";
  if (memcmp(s, MAIN_CLOSED, 8) == 0) return "MAIN_CLOSED";
  if (memcmp(s, OPEN_BEGIN, 8) == 0) return "OPEN_BEGIN";
  return "STATE_UNKNOWN";
}

static bool canInit() {
  twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(
      static_cast<gpio_num_t>(CAN_TX_PIN),
      static_cast<gpio_num_t>(CAN_RX_PIN),
      TWAI_MODE_NORMAL);

  // TX queue must be non-zero for command/test transmission.
  g_config.tx_queue_len = 24;
  g_config.rx_queue_len = 64;

  twai_timing_config_t t_config;
  switch (CAN_BITRATE) {
    case 1000000:
      t_config = TWAI_TIMING_CONFIG_1MBITS();
      break;
    case 500000:
      t_config = TWAI_TIMING_CONFIG_500KBITS();
      break;
    case 250000:
      t_config = TWAI_TIMING_CONFIG_250KBITS();
      break;
    case 125000:
      t_config = TWAI_TIMING_CONFIG_125KBITS();
      break;
    default:
      Serial.printf("Unsupported CAN_BITRATE=%d, fallback 500k\n", CAN_BITRATE);
      t_config = TWAI_TIMING_CONFIG_500KBITS();
      break;
  }

  twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

  if (twai_driver_install(&g_config, &t_config, &f_config) != ESP_OK) return false;
  if (twai_start() != ESP_OK) {
    twai_driver_uninstall();
    return false;
  }
  return true;
}

// Silent transmit – no serial echo; used by high-rate keepalive loops
static bool sendStdSilent(uint32_t id, const uint8_t *data, uint8_t dlc) {
  if (dlc > 8) return false;
  twai_message_t msg = {};
  msg.identifier = id;
  msg.extd = 0; msg.rtr = 0; msg.self = 0; msg.ss = 0;
  msg.data_length_code = dlc;
  for (uint8_t i = 0; i < dlc; i++) msg.data[i] = data[i];
  return twai_transmit(&msg, pdMS_TO_TICKS(10)) == ESP_OK;
}

static bool sendStd(uint32_t id, const uint8_t *data, uint8_t dlc) {
  if (dlc > 8) return false;
  twai_message_t msg = {};
  msg.identifier = id;
  msg.extd = 0;
  msg.rtr = 0;
  msg.self = 0;
  msg.ss = 0;
  msg.data_length_code = dlc;
  for (uint8_t i = 0; i < dlc; i++) msg.data[i] = data[i];

  esp_err_t e = twai_transmit(&msg, pdMS_TO_TICKS(50));
  if (e != ESP_OK) {
    Serial.printf("[TX] FAIL ID=0x%03lX err=%d\n", id, static_cast<int>(e));
    return false;
  }

  char hex[32];
  bytesToHex(data, dlc, hex, sizeof(hex));
  Serial.printf("[TX] OK   ID=0x%03lX DLC=%u DATA=%s\n", id, dlc, hex);
  return true;
}

static bool send281Step(uint8_t b0, uint8_t c1, uint8_t c2, uint8_t c3, uint8_t c4) {
  uint8_t p[5] = {b0, c1, c2, c3, c4};
  return sendStd(ID_281, p, 5);
}

static void printHelp() {
  Serial.println();
  Serial.println("==== e3008 CAN Test Tool Menu ====");
  Serial.println("help                     : show this menu");
  Serial.println("status                   : print current decoded status");
  Serial.println("cells                    : print decoded cell voltages");
  Serial.println("temps                    : print decoded temperatures");
  Serial.println("raw 0|1                  : disable/enable raw RX print");
  Serial.println("stream 0|1               : disable/enable periodic telemetry print");
  Serial.println("tx <idHex> <payloadHex>  : send one CAN frame (std ID, <=8 bytes)");
  Serial.println("step281 <b0hex> <ctx4B>  : send one 0x281 step; ctx4B example 57000000");
  Serial.println("close                    : start close_short sequence (31,44,AE)");
  Serial.println("close6                   : start full close sequence (31,44,55,8F,A0,AE)");
  Serial.println("open                     : start open_short sequence (85,11,8A,F3)");
  Serial.println("open6                    : start full open sequence (85,11,8A,99,D5,F3)");
  Serial.println("seqstop                  : stop active sequence");
  Serial.println("keepalive on|off         : start/stop 0x281 hold + 0x428 watchdog");
  Serial.println("hold on|off              : enable/disable 0x281 hold only (@135ms)");
  Serial.println("wd on|off                : enable/disable 0x428 watchdog only (@58ms)");
  Serial.println("watch                    : print latest 0x428 / 0x353 / 0x591 summary");
  Serial.println("reboot                   : restart controller");
  Serial.println("==================================");
}

static void printStatus() {
  char s591hex[24] = "<none>";
  if (g_t.state591Valid) {
    bytesToHex(g_t.state591, 8, s591hex, sizeof(s591hex));
  }

  Serial.println();
  Serial.println("---- STATUS ----");
  Serial.printf("RX total=%lu interesting=%lu lastRx=%lums\n",
                static_cast<unsigned long>(g_t.rxFrames),
                static_cast<unsigned long>(g_t.rxInteresting),
                static_cast<unsigned long>(g_t.lastRxMs));
  Serial.printf("0x583 raw0=%u raw1=%u\n", g_t.battRaw0, g_t.battRaw1);
  Serial.printf("0x353 socByte=%u valid=%d\n", g_t.socByte, g_t.socValid ? 1 : 0);
  Serial.printf("0x428 byte0=%u valid=%d\n", g_t.watchdog428, g_t.watchdogValid ? 1 : 0);
  if (g_t.torqueValid) {
    uint16_t torqueRaw = static_cast<uint16_t>(g_t.torqueRawHi) << 8 | g_t.torqueRawLo;
    Serial.printf("0x154 torqueRaw=%u\n", torqueRaw);
  }
  Serial.printf("0x591=%s (%s), lastChange=%lums\n",
                s591hex,
                g_t.state591Valid ? state591Name(g_t.state591) : "N/A",
                static_cast<unsigned long>(g_t.last591ChangeMs));
  Serial.printf("Seq active=%d name=%s step=%u/%u\n",
                g_seq.active ? 1 : 0,
                g_seq.name,
                static_cast<unsigned>(g_seq.index),
                static_cast<unsigned>(g_seq.len));
  Serial.printf("KP hold281=%d b0=0x%02X  wd428=%d b0=0x%02X\n",
                g_kp281 ? 1 : 0, g_kp281B0,
                g_kp428 ? 1 : 0, g_kp428B0);
  Serial.println("----------------");
}

static void printCells() {
  Serial.println("[cells] decoded values:");
  uint16_t shown = 0;
  for (uint16_t i = 0; i < MAX_CELLS; i++) {
    if (!g_t.cellValid[i]) continue;
    Serial.printf("C%u=%umV ", i + 1U, g_t.cellmV[i]);
    shown++;
    if ((shown % 6U) == 0U) Serial.println();
  }
  if (shown == 0) Serial.println("<none>");
  else if ((shown % 6U) != 0U) Serial.println();
}

static void printTemps() {
  Serial.println("[temps] decoded values:");
  uint16_t shown = 0;
  for (uint16_t i = 0; i < MAX_TEMPS; i++) {
    if (!g_t.tempValid[i]) continue;
    Serial.printf("T%u=%dC ", i + 1U, g_t.tempC[i]);
    shown++;
    if ((shown % 8U) == 0U) Serial.println();
  }
  if (shown == 0) Serial.println("<none>");
  else if ((shown % 8U) != 0U) Serial.println();
}

static void decode583(const twai_message_t &msg) {
  if (msg.data_length_code < 2) return;
  g_t.battRaw0 = msg.data[0];
  g_t.battRaw1 = msg.data[1];
  g_t.rxInteresting++;
}

static void decode334(const twai_message_t &msg) {
  if (msg.data_length_code < 7) return;

  const uint8_t mux = msg.data[0] >> 3;
  if (mux == 0) return;

  const uint16_t w1 = (static_cast<uint16_t>(msg.data[1]) << 8) | msg.data[2];
  const uint16_t w2 = (static_cast<uint16_t>(msg.data[3]) << 8) | msg.data[4];
  const uint16_t w3 = (static_cast<uint16_t>(msg.data[5]) << 8) | msg.data[6];

  const uint16_t v1mV = w1 >> 2;
  const uint16_t v2mV = w2 >> 4;
  const uint16_t v3mV = w3 >> 4;

  const uint16_t idxBase = static_cast<uint16_t>((mux - 1U) * 3U);
  if (idxBase < MAX_CELLS) {
    g_t.cellmV[idxBase] = v1mV;
    g_t.cellValid[idxBase] = true;
  }
  if (idxBase + 1U < MAX_CELLS) {
    g_t.cellmV[idxBase + 1U] = v2mV;
    g_t.cellValid[idxBase + 1U] = true;
  }
  if (idxBase + 2U < MAX_CELLS) {
    g_t.cellmV[idxBase + 2U] = v3mV;
    g_t.cellValid[idxBase + 2U] = true;
  }
  g_t.rxInteresting++;
}

static void decode3F4(const twai_message_t &msg) {
  if (msg.data_length_code < 8) return;

  const uint8_t slot = msg.data[0] >> 6;
  const uint16_t idxBase = static_cast<uint16_t>(slot * 7U);
  for (uint8_t i = 0; i < 7; i++) {
    const uint16_t idx = idxBase + i;
    if (idx >= MAX_TEMPS) break;
    const uint8_t raw = msg.data[i + 1U];
    g_t.tempC[idx] = static_cast<int16_t>(raw) - 40;
    g_t.tempValid[idx] = true;
  }
  g_t.rxInteresting++;
}

static void decode353(const twai_message_t &msg) {
  if (msg.data_length_code >= 4) {
    g_t.socByte = msg.data[3];
    g_t.socValid = true;
  }
  g_t.rxInteresting++;
}

static void decode428(const twai_message_t &msg) {
  if (msg.data_length_code >= 1) {
    g_t.watchdog428 = msg.data[0];
    g_t.watchdogValid = true;
  }
  g_t.rxInteresting++;
}

static void decode591(const twai_message_t &msg) {
  if (msg.data_length_code < 8) return;
  if (!g_t.state591Valid || memcmp(g_t.state591, msg.data, 8) != 0) {
    memcpy(g_t.state591, msg.data, 8);
    g_t.state591Valid = true;
    g_t.last591ChangeMs = millis();

    char h[24];
    bytesToHex(msg.data, 8, h, sizeof(h));
    Serial.printf("[0x591] state=%s (%s)\n", h, state591Name(msg.data));
  }
  g_t.rxInteresting++;
}

static void decode154(const twai_message_t &msg) {
  if (msg.data_length_code >= 2) {
    g_t.torqueRawLo = msg.data[0];
    g_t.torqueRawHi = msg.data[1];
    g_t.torqueValid = true;
  }
  g_t.rxInteresting++;
}

// ── Keepalive management ────────────────────────────────────────────────────
static void enableKeepalive() {
  g_kp281 = true;
  g_kp281B0 = 0xDB;
  g_kp281NextMs = millis() + KP_281_INTERVAL_MS;
  g_kp428 = true;
  g_kp428B0 = 0xC2;
  g_kp428NextMs = millis() + KP_428_INTERVAL_MS;
  Serial.println("[KP] keepalive ON  0x281 hold @135ms + 0x428 wd @58ms");
}

static void disableKeepalive() {
  if (g_kp281 || g_kp428) {
    g_kp281 = false;
    g_kp428 = false;
    Serial.println("[KP] keepalive OFF");
  }
}

static void updateKeepalive281() {
  if (!g_kp281) return;
  const uint32_t now = millis();
  if (static_cast<int32_t>(now - g_kp281NextMs) < 0) return;
  uint8_t p[5] = {g_kp281B0,
                  KP_281_HOLD_CTX[0], KP_281_HOLD_CTX[1],
                  KP_281_HOLD_CTX[2], KP_281_HOLD_CTX[3]};
  sendStdSilent(ID_281, p, 5);
  g_kp281B0 -= 0x0F;  // roll byte0 -0x0F every 135 ms
  g_kp281NextMs = now + KP_281_INTERVAL_MS;
}

static void updateKeepalive428() {
  if (!g_kp428) return;
  const uint32_t now = millis();
  if (static_cast<int32_t>(now - g_kp428NextMs) < 0) return;
  uint8_t p[8] = {g_kp428B0, 0x01, 0xA8, 0x00, 0x00, 0x00, 0x00, 0x00};
  sendStdSilent(ID_428, p, 8);
  g_kp428B0 -= 0x0F;  // roll byte0 -0x0F every 58 ms
  g_kp428NextMs = now + KP_428_INTERVAL_MS;
}

static void startSequence(const char *name,
                          const uint8_t *values,
                          const uint32_t *delays,
                          uint8_t len,
                          const uint8_t ctx[4]) {
  if (len == 0 || len > 12) return;
  memset(&g_seq, 0, sizeof(g_seq));
  g_seq.active = true;
  strncpy(g_seq.name, name, sizeof(g_seq.name) - 1U);
  for (uint8_t i = 0; i < len; i++) {
    g_seq.values[i] = values[i];
    g_seq.delaysMs[i] = delays[i];
  }
  g_seq.len = len;
  memcpy(g_seq.ctx, ctx, 4);
  g_seq.nextStepAt = millis();
  Serial.printf("[SEQ] started '%s' len=%u\n", g_seq.name, static_cast<unsigned>(g_seq.len));
}

static void stopSequence() {
  if (g_seq.active) {
    Serial.printf("[SEQ] stopped '%s' at step %u/%u\n", g_seq.name,
                  static_cast<unsigned>(g_seq.index),
                  static_cast<unsigned>(g_seq.len));
  }
  memset(&g_seq, 0, sizeof(g_seq));
}

static void updateSequence() {
  if (!g_seq.active) return;

  const uint32_t now = millis();
  if (static_cast<int32_t>(now - g_seq.nextStepAt) < 0) return;

  if (g_seq.index >= g_seq.len) {
    Serial.printf("[SEQ] done '%s'\n", g_seq.name);
    stopSequence();
    return;
  }

  const uint8_t b0 = g_seq.values[g_seq.index];
  send281Step(b0, g_seq.ctx[0], g_seq.ctx[1], g_seq.ctx[2], g_seq.ctx[3]);

  const uint32_t wait = g_seq.delaysMs[g_seq.index];
  g_seq.index++;
  g_seq.nextStepAt = now + wait;

  if (g_seq.index >= g_seq.len) {
    Serial.printf("[SEQ] completed '%s'\n", g_seq.name);
    if (strncmp(g_seq.name, "close", 5) == 0) {
      enableKeepalive();  // auto-hold after close sequence finishes
    }
  }
}

static bool parseHexPayload(const char *in, uint8_t *out, uint8_t &outLen) {
  outLen = 0;
  const size_t n = strlen(in);
  if ((n == 0) || (n % 2) != 0 || n > 16) return false;

  for (size_t i = 0; i < n; i++) {
    if (!isHexChar(in[i])) return false;
  }

  for (size_t i = 0; i < n; i += 2) {
    char b[3] = {in[i], in[i + 1], 0};
    out[outLen++] = static_cast<uint8_t>(strtoul(b, nullptr, 16));
  }
  return true;
}

static void cmdCloseShort() {
  // Short practical progression from findings
  static const uint8_t vals[] = {0x31, 0x44, 0xAE};
  static const uint32_t dly[] = {40, 1300, 0};
  static const uint8_t ctx[] = {0x57, 0x00, 0x00, 0x00};
  startSequence("close_short", vals, dly, sizeof(vals), ctx);
}

static void cmdCloseFull() {
  static const uint8_t vals[] = {0x31, 0x44, 0x55, 0x8F, 0xA0, 0xAE};
  static const uint32_t dly[] = {80, 80, 80, 80, 80, 0};
  static const uint8_t ctx[] = {0x57, 0x00, 0x00, 0x00};
  startSequence("close_full", vals, dly, sizeof(vals), ctx);
}

static void cmdOpenShort() {
  disableKeepalive();  // stop hold before commanding open
  static const uint8_t vals[] = {0x85, 0x11, 0x8A, 0xF3};
  static const uint32_t dly[] = {1100, 3000, 61000, 0};
  static const uint8_t ctx[] = {0x6C, 0x0D, 0x80, 0x00};
  startSequence("open_short", vals, dly, sizeof(vals), ctx);
}

static void cmdOpenFull() {
  disableKeepalive();  // stop hold before commanding open
  static const uint8_t vals[] = {0x85, 0x11, 0x8A, 0x99, 0xD5, 0xF3};
  static const uint32_t dly[] = {1100, 3000, 1000, 61000, 53600, 0};
  static const uint8_t ctx[] = {0x6C, 0x0D, 0x80, 0x00};
  startSequence("open_full", vals, dly, sizeof(vals), ctx);
}

static void handleLine(char *line) {
  while (*line == ' ' || *line == '\t') line++;
  if (*line == '\0') return;

  char *argv[8] = {nullptr};
  uint8_t argc = 0;

  char *tok = strtok(line, " \t\r\n");
  while (tok && argc < 8) {
    argv[argc++] = tok;
    tok = strtok(nullptr, " \t\r\n");
  }

  if (argc == 0) return;

  if (strcmp(argv[0], "help") == 0 || strcmp(argv[0], "?") == 0) {
    printHelp();
    return;
  }
  if (strcmp(argv[0], "status") == 0) {
    printStatus();
    return;
  }
  if (strcmp(argv[0], "cells") == 0) {
    printCells();
    return;
  }
  if (strcmp(argv[0], "temps") == 0) {
    printTemps();
    return;
  }
  if (strcmp(argv[0], "watch") == 0) {
    Serial.printf("watch: 0x428=%u valid=%d, 0x353=%u valid=%d\n",
                  g_t.watchdog428,
                  g_t.watchdogValid ? 1 : 0,
                  g_t.socByte,
                  g_t.socValid ? 1 : 0);
    if (g_t.state591Valid) {
      char h[24];
      bytesToHex(g_t.state591, 8, h, sizeof(h));
      Serial.printf("watch: 0x591=%s (%s)\n", h, state591Name(g_t.state591));
    }
    Serial.printf("watch: hold281=%d b0=0x%02X  wd428=%d b0=0x%02X\n",
                  g_kp281 ? 1 : 0, g_kp281B0, g_kp428 ? 1 : 0, g_kp428B0);
    return;
  }
  if (strcmp(argv[0], "raw") == 0 && argc >= 2) {
    g_rawPrint = (atoi(argv[1]) != 0);
    Serial.printf("raw=%d\n", g_rawPrint ? 1 : 0);
    return;
  }
  if (strcmp(argv[0], "stream") == 0 && argc >= 2) {
    g_streamTelemetry = (atoi(argv[1]) != 0);
    Serial.printf("stream=%d\n", g_streamTelemetry ? 1 : 0);
    return;
  }
  if (strcmp(argv[0], "seqstop") == 0) {
    stopSequence();
    return;
  }
  if (strcmp(argv[0], "close") == 0) {
    cmdCloseShort();
    return;
  }
  if (strcmp(argv[0], "close6") == 0) {
    cmdCloseFull();
    return;
  }
  if (strcmp(argv[0], "open") == 0) {
    cmdOpenShort();
    return;
  }
  if (strcmp(argv[0], "open6") == 0) {
    cmdOpenFull();
    return;
  }
  if (strcmp(argv[0], "reboot") == 0) {
    Serial.println("Rebooting...");
    delay(200);
    ESP.restart();
    return;
  }

  if (strcmp(argv[0], "step281") == 0 && argc >= 3) {
    uint8_t b0 = static_cast<uint8_t>(strtoul(argv[1], nullptr, 16));
    uint8_t ctx[8];
    uint8_t len = 0;
    if (!parseHexPayload(argv[2], ctx, len) || len != 4) {
      Serial.println("ERR: step281 ctx must be exactly 4 bytes hex (example 57000000)");
      return;
    }
    send281Step(b0, ctx[0], ctx[1], ctx[2], ctx[3]);
    return;
  }

  if (strcmp(argv[0], "tx") == 0 && argc >= 3) {
    uint32_t id = strtoul(argv[1], nullptr, 16);
    if (id > 0x7FFU) {
      Serial.println("ERR: std ID only (<=0x7FF)");
      return;
    }
    uint8_t data[8];
    uint8_t len = 0;
    if (!parseHexPayload(argv[2], data, len)) {
      Serial.println("ERR: payload must be even hex chars, max 16 chars");
      return;
    }
    sendStd(id, data, len);
    return;
  }

  if (strcmp(argv[0], "keepalive") == 0 && argc >= 2) {
    bool en = (strcmp(argv[1], "on") == 0 || atoi(argv[1]) != 0);
    if (en) enableKeepalive(); else disableKeepalive();
    return;
  }
  if (strcmp(argv[0], "hold") == 0 && argc >= 2) {
    bool en = (strcmp(argv[1], "on") == 0 || atoi(argv[1]) != 0);
    g_kp281 = en;
    if (en) { g_kp281NextMs = millis() + KP_281_INTERVAL_MS; }
    Serial.printf("hold=%d\n", g_kp281 ? 1 : 0);
    return;
  }
  if (strcmp(argv[0], "wd") == 0 && argc >= 2) {
    bool en = (strcmp(argv[1], "on") == 0 || atoi(argv[1]) != 0);
    g_kp428 = en;
    if (en) { g_kp428NextMs = millis() + KP_428_INTERVAL_MS; }
    Serial.printf("wd=%d\n", g_kp428 ? 1 : 0);
    return;
  }

  Serial.println("Unknown command. Type 'help'.");
}

static void processSerial() {
  while (Serial.available() > 0) {
    char c = static_cast<char>(Serial.read());
    if (c == '\r') continue;
    if (c == '\n') {
      g_lineBuf[g_lineLen] = '\0';
      handleLine(g_lineBuf);
      g_lineLen = 0;
      continue;
    }
    if (g_lineLen + 1 < LINE_BUF_SZ) {
      g_lineBuf[g_lineLen++] = c;
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(400);

  Serial.println();
  Serial.println("e3008 CAN Telemetry + Contactor Control Test Tool (ESP32-S3 TWAI)");
  Serial.printf("Pins TX=%d RX=%d STBY=%d bitrate=%d\n",
                CAN_TX_PIN, CAN_RX_PIN, CAN_STBY_PIN, CAN_BITRATE);

#if CAN_STBY_PIN >= 0
  pinMode(CAN_STBY_PIN, OUTPUT);
  digitalWrite(CAN_STBY_PIN, LOW);
#endif

  if (!canInit()) {
    Serial.println("TWAI init failed");
    while (true) delay(1000);
  }

  printHelp();
}

void loop() {
  processSerial();
  updateSequence();
  updateKeepalive281();
  updateKeepalive428();

  twai_message_t msg;
  while (twai_receive(&msg, 0) == ESP_OK) {
    if (msg.extd || msg.rtr) continue;

    g_t.rxFrames++;
    g_t.lastRxMs = millis();

    if (g_rawPrint) printFrame(msg);

    switch (msg.identifier) {
      case ID_154:
        decode154(msg);
        break;
      case ID_281:
        g_t.rxInteresting++;
        break;
      case ID_334:
        decode334(msg);
        break;
      case ID_353:
        decode353(msg);
        break;
      case ID_3F4:
        decode3F4(msg);
        break;
      case ID_428:
        decode428(msg);
        break;
      case ID_583:
        decode583(msg);
        break;
      case ID_591:
        decode591(msg);
        break;
      default:
        break;
    }
  }

  const uint32_t now = millis();
  if (g_streamTelemetry && (now - g_lastPeriodicStatus >= 3000U)) {
    g_lastPeriodicStatus = now;

    uint16_t cCount = 0;
    uint16_t tCount = 0;
    uint32_t cMin = 65535;
    uint32_t cMax = 0;

    for (uint16_t i = 0; i < MAX_CELLS; i++) {
      if (!g_t.cellValid[i]) continue;
      cCount++;
      if (g_t.cellmV[i] < cMin) cMin = g_t.cellmV[i];
      if (g_t.cellmV[i] > cMax) cMax = g_t.cellmV[i];
    }
    for (uint16_t i = 0; i < MAX_TEMPS; i++) {
      if (g_t.tempValid[i]) tCount++;
    }

    char s591hex[24] = "N/A";
    const char *s591n = "N/A";
    if (g_t.state591Valid) {
      bytesToHex(g_t.state591, 8, s591hex, sizeof(s591hex));
      s591n = state591Name(g_t.state591);
    }

    Serial.printf("[tele] cells=%u range=%lu..%lumV temps=%u soc=%u wd=0x%02X state591=%s(%s) seq=%s kp=%s\n",
                  static_cast<unsigned>(cCount),
                  static_cast<unsigned long>(cCount ? cMin : 0),
                  static_cast<unsigned long>(cCount ? cMax : 0),
                  static_cast<unsigned>(tCount),
                  static_cast<unsigned>(g_t.socByte),
                  static_cast<unsigned>(g_t.watchdog428),
                  s591hex,
                  s591n,
                  g_seq.active ? g_seq.name : "idle",
                  (g_kp281 || g_kp428) ? "ON" : "off");
  }

  delay(1);
}
