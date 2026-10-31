# Manual supply voltage

The button at the bottom of **Servo setup** reads the selected servo's supply
voltage once. The ID defaults to 32 and accepts 0–253. Opening the page, refreshing
status or restarting the app never samples voltage automatically. Results show
the actual servo ID and measurement age. This is uncalibrated servo-terminal
voltage, including wiring drop, not battery-terminal voltage or state of charge.

## Reuse of upstream servo operations

`POST /api/voltage/read` accepts `{"servo_id":32}`; omitting the ID defaults to 32.
Python uses the existing `duck_servo` request and `duck_servo_reply` response,
servo-operation lock, reply event and timeout handling. The API request waits for
the response (up to two seconds), outside the policy loop and controller lock.
The unchanged webpage displays pending/result state through `/api/status`.

The only new MCU operation is `SERVO_READ_BYTE = 11`. It uses the existing
`receiveServo` → `pendingServo` → `applyServoOp` → `publishServoReply` path.
There is no separate register RPC, queue, result snapshot or reporting loop.
This read-only operation is allowed in normal and servo-debug modes without
changing mode or torque. It is rejected during calibration or a mid-reset.
Other servo operations retain their original debug-mode requirements.

The packet sizes and magic remain unchanged:

| Packet | Layout | Byte-read field use |
| --- | --- | --- |
| Servo request | `DQV2`, 12 bytes, `<4sBBBBBBH>` | op=11, target ID, newId/kp/kd=0, reserved byte=address, reserved word=request ID |
| Servo reply | `DQS3`, 14 bytes, `<4sBBBBHHBB>` | op=11, target ID, ok, reserved byte=address, rawPos word=byte value, centerPos word=request ID, kp/kd=0 |

The nonzero 16-bit request ID and echoed address distinguish late replies from
new reads of the same servo. Python validates op, ID, address and request ID.
Zero and 255 are valid generic register bytes; only the Python voltage layer
rejects them and converts valid voltage values at address `0x3E` by dividing by 10.
The `ok` field distinguishes a failed read from a successful read of zero.

Both Python and MCU limit reads to once per second. Python serializes voltage
reads with Servo setup operations and coalesces duplicate clicks while pending.
Timeout, invalid replies and send failures release the shared operation lock.
Changing modes concurrently may supersede the queued read and cause a timeout;
a voltage request never sends a mode or motor-enable command.

## Minimal bus extension

`scsReadByte(id, address, out, timeoutUs)` reuses the upstream packet sender and
parser. The parser accepts one-byte replies and optionally returns the first
matching byte, or -1. No transaction structure or extra global state is added.
Checksum, device error, ID and length checks remain. The helper waits at most
approximately 1 ms for a reply, only on the servo task. Normal feedback remains
six bytes at 0x38–0x3D; position, KP/KD and broadcast reads retain upstream logic.

## Deployment and validation

MCU and Python must be updated together. Older firmware rejects op 11. This
replaces the previous independent register/electric-voltage RPC implementation;
the webpage API and DQS1 movement ABI are unchanged.

- `python3 -m unittest discover -s tests -p test_voltage.py -v`
- `node tests/voltage_ui.cjs`
- `clang++ -std=c++17 -I tests/arduino_stub tests/voltage_bus.cpp -o /tmp/xgo-voltage-test`
- `/tmp/xgo-voltage-test`

Tests cover shared servo RPC compatibility, serialization, duplicate clicks,
wrong/late responses, timeout cleanup, ID validation, historical age, default
manual behavior and actual UART parsing with mocked UART/time. Hardware timing
and motion behavior require separate device validation.
