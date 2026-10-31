import sys, time, threading, unittest, struct
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
import controller
from wire import (SERVO, SERVO_REPLY, SERVO_READ_BYTE, SERVO_READ, VOLTAGE_ADDRESS,
                  encode_servo, encode_servo_read_byte, decode_servo_reply, STATE, decode_state)


def connected_controller():
    c = controller.Controller(Mock())
    raw = bytearray(STATE.size)
    struct.pack_into('<4sBBH', raw, 0, b'DQS1', 1, 1, 0x7fff)
    c.feedback = decode_state(raw)
    c.rx_time = time.monotonic()
    return c


def reply(request_id, sid=32, address=0x3e, value=74, ok=1):
    return SERVO_REPLY.pack(b'DQS3', SERVO_READ_BYTE, sid, ok, address, value, request_id, 0, 0)


def responding(c, value=74, ok=1):
    def notify(method, payload):
        magic, op, sid, new_id, kp, kd, address, token = SERVO.unpack(payload)
        assert (method, magic, op, new_id, kp, kd) == ('duck_servo', b'DQV2', SERVO_READ_BYTE, 0, 0, 0)
        c.receive_servo_reply(reply(token, sid, address, value, ok))
    c.bridge.notify.side_effect = notify


class VoltageTests(unittest.TestCase):
    def test_existing_servo_packet_sizes_and_codec(self):
        self.assertEqual((SERVO.size, SERVO_REPLY.size), (12, 14))
        self.assertEqual(encode_servo_read_byte(123, 0, 255),
                         SERVO.pack(b'DQV2', 11, 0, 0, 0, 0, 255, 123))
        for args in ((0,32,62), (65536,32,62), (1,254,62), (1,32,256), (1,True,62)):
            with self.assertRaises(ValueError): encode_servo_read_byte(*args)
        for value in (0, 255):
            self.assertEqual(decode_servo_reply(reply(1, value=value))['value'], value)
        for raw in (reply(0), reply(1, value=256), reply(1, ok=2), reply(1, sid=254), reply(1)[:-1]):
            with self.assertRaises(ValueError): decode_servo_reply(raw)
        with self.assertRaises(ValueError): encode_servo(SERVO_READ_BYTE, 32)

    def test_manual_read_uses_existing_rpc_and_does_not_change_mode(self):
        for sid in (0, 31, 32, 253):
            c = connected_controller()
            self.assertFalse(c.status()['supply_voltage']['available'])
            c.bridge.notify.assert_not_called()
            responding(c)
            result = c.request_voltage(sid)
            self.assertTrue(result['accepted']); self.assertFalse(result['pending'])
            c.bridge.notify.assert_called_once_with('duck_servo', encode_servo_read_byte(result['request_id'], sid, VOLTAGE_ADDRESS))
            v = c.status()['supply_voltage']
            self.assertEqual((v['servo_id'], v['volts']), (sid, 7.4))
            self.assertEqual(c.mode, 'shadow')
            self.assertIsNone(c.servo_expected_reply)
            self.assertFalse(c.servo_op_lock.locked())
            with self.assertRaises(ValueError): c.request_voltage(sid)
            c.voltage_rx_time -= 60
            self.assertGreaterEqual(c.status()['supply_voltage']['age_ms'], 60000)
            self.assertEqual(c.bridge.notify.call_count, 1)

    def test_wrong_and_late_replies_cannot_complete_read(self):
        c = connected_controller()
        def notify(method, payload):
            *_, token = SERVO.unpack(payload)
            for raw in (reply(token, sid=31), reply(token, address=0x30), reply(token ^ 1 or 2),
                        SERVO_REPLY.pack(b'DQS3', SERVO_READ, 32, 1, 0, 2048, 2047, 5, 10)):
                c.receive_servo_reply(raw)
                self.assertFalse(c.servo_reply_event.is_set())
            c.receive_servo_reply(reply(token))
        c.bridge.notify.side_effect = notify
        token = c.request_voltage()['request_id']
        c.receive_servo_reply(reply(token, value=90))
        self.assertEqual(c.status()['supply_voltage']['volts'], 7.4)

    def test_timeout_cleanup_and_retry(self):
        c = connected_controller()
        with patch('controller.VOLTAGE_REQUEST_TIMEOUT_S', .01):
            with self.assertRaisesRegex(ValueError, '超时'): c.request_voltage()
        self.assertFalse(c.servo_op_lock.locked())
        self.assertIsNone(c.servo_expected_reply)
        old = c.voltage_request_seq
        c.voltage_requested_at -= 2
        c.rx_time = time.monotonic()
        def notify(method, payload):
            c.receive_servo_reply(reply(old))
            self.assertFalse(c.servo_reply_event.is_set())
            c.receive_servo_reply(reply(SERVO.unpack(payload)[-1]))
        c.bridge.notify.side_effect = notify
        c.request_voltage()
        self.assertEqual(c.status()['supply_voltage']['volts'], 7.4)

    def test_invalid_values_device_error_and_send_failure(self):
        for value, ok in ((0,1), (255,1), (74,0)):
            c = connected_controller(); responding(c, value, ok)
            if ok: c.request_voltage()
            else:
                with self.assertRaisesRegex(ValueError, '未返回有效电压'): c.request_voltage()
            v = c.status()['supply_voltage']
            self.assertFalse(v['available']); self.assertFalse(v['pending'])
            self.assertFalse(c.servo_op_lock.locked())
        c = connected_controller(); c.bridge.notify.side_effect = RuntimeError('offline')
        with self.assertRaisesRegex(ValueError, '发送失败'): c.request_voltage()
        self.assertFalse(c.servo_op_lock.locked())
        self.assertIsNone(c.servo_expected_reply)

    def test_existing_servo_operation_and_voltage_are_serialized(self):
        c = connected_controller()
        with c.servo_op_lock:
            with self.assertRaisesRegex(ValueError, '舵机操作进行中'): c.request_voltage()
        c.mode = 'servo_debug'
        c.bridge.notify.side_effect = lambda *_: c.receive_servo_reply(
            SERVO_REPLY.pack(b'DQS3', SERVO_READ, 32, 1, 0, 2048, 2047, 5, 10))
        r = c.servo_op('read', 32)
        self.assertEqual((r['raw_pos'], r['kp'], r['kd']), (2048, 5, 10))
        responding(c); c.request_voltage()
        self.assertEqual(c.mode, 'servo_debug')

    def test_duplicate_click_coalesces_while_waiting(self):
        c = connected_controller(); sent = threading.Event(); errors = []
        c.bridge.notify.side_effect = lambda *_: sent.set()
        def run():
            try: c.request_voltage()
            except Exception as exc: errors.append(exc)
        worker = threading.Thread(target=run); worker.start()
        try:
            self.assertTrue(sent.wait(1))
            self.assertFalse(c.request_voltage()['accepted'])
            with self.assertRaises(ValueError): c.request_voltage(31)
            self.assertEqual(c.bridge.notify.call_count, 1)
            c.receive_servo_reply(reply(c.voltage_pending))
        finally:
            worker.join(3)
        self.assertFalse(worker.is_alive()); self.assertEqual(errors, [])

    def test_invalid_id_disconnected_and_calibration_do_not_send(self):
        c = connected_controller()
        for sid in (-1,254,255,1.5,True,'32',None):
            with self.assertRaises(ValueError): c.request_voltage(sid)
        c.mode = 'calibrate'
        with self.assertRaisesRegex(ValueError, '校准'): c.request_voltage()
        c.mode = 'shadow'; c.rx_time -= 1
        with self.assertRaisesRegex(ValueError, '未连接'): c.request_voltage()
        c.bridge.notify.assert_not_called()
        self.assertFalse(c.servo_op_lock.locked())


if __name__ == '__main__': unittest.main()
