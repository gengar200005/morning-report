import contextlib
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from googleapiclient.errors import HttpError
from validation.trend_audit.krx_pit_private import drive_retry as m

def error(status, reason="unknown"):
    return HttpError(SimpleNamespace(status=status, reason="secret URL"),
        json.dumps({"error":{"errors":[{"reason":reason,"message":"SECRET"}]}}).encode(),
        uri="https://private.example/SECRET")

class RetryTests(unittest.TestCase):
    def test_retry_status_and_reason_allowlist(self):
        for status, reason, expected in [
            (429,"unknown",True),(503,"unknown",True),
            (403,"rateLimitExceeded",True),(403,"userRateLimitExceeded",True),
            (403,"storageQuotaExceeded",False),(403,"dailyLimitExceeded",False),
            (403,"insufficientPermissions",False),(401,"authError",False),
            (400,"invalid",False)]:
            self.assertEqual(m.retryable(error(status,reason)),expected)
    @patch.object(m,"pause")
    def test_bounded_read_retries(self, pause):
        call=Mock(side_effect=[error(503),error(429),42])
        self.assertEqual(m.read_retry(call),42)
        self.assertEqual(call.call_count,3)
        call=Mock(side_effect=error(401,"authError"))
        with self.assertRaises(HttpError): m.read_retry(call)
        self.assertEqual(call.call_count,1)
        call=Mock(side_effect=error(503))
        with self.assertRaises(HttpError): m.read_retry(call)
        self.assertEqual(call.call_count,6)
    def test_log_does_not_reflect_secrets(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out): m.log_error(error(403,"SECRET"),"upload",1)
        self.assertNotIn("SECRET",out.getvalue())
        self.assertNotIn("https",out.getvalue())
        self.assertIn("http=403",out.getvalue())
    def setup_drive(self):
        drive=Mock()
        drive.files.return_value.generateIds.return_value.execute.return_value={"ids":["fixed"]}
        return drive
    def test_success_verified(self):
        drive=self.setup_drive(); obj={"id":"fixed"}
        drive.files.return_value.create.return_value.execute.return_value=obj
        verify=Mock()
        self.assertEqual(m.upload_archive(drive,"folder","month","hash",b"abc",
                         Mock(return_value=None),verify),obj)
        verify.assert_called_once_with(obj)
    def test_existing_archive_no_create(self):
        drive=self.setup_drive();verify=Mock()
        m.upload_archive(drive,"folder","month","hash",b"abc",
                         Mock(return_value={"id":"old"}),verify)
        drive.files.return_value.create.assert_not_called()
        verify.assert_called_once_with({"id":"old"})
    def test_committed_response_lost_recovered(self):
        drive=self.setup_drive()
        drive.files.return_value.create.return_value.execute.side_effect=TimeoutError()
        drive.files.return_value.get.return_value.execute.return_value={"id":"fixed"}
        verify=Mock()
        m.upload_archive(drive,"folder","month","hash",b"abc",Mock(return_value=None),verify)
        self.assertEqual(drive.files.return_value.create.call_count,1)
        verify.assert_called_once_with({"id":"fixed"})
    @patch.object(m,"pause")
    def test_uncommitted_retry_reuses_id(self, pause):
        drive=self.setup_drive()
        drive.files.return_value.create.return_value.execute.side_effect=[error(503),{"id":"fixed"}]
        drive.files.return_value.get.return_value.execute.side_effect=error(404,"notFound")
        m.upload_archive(drive,"folder","month","hash",b"abc",Mock(return_value=None),Mock())
        ids=[c.kwargs["body"]["id"] for c in drive.files.return_value.create.call_args_list]
        self.assertEqual(ids,["fixed","fixed"])
        self.assertEqual(drive.files.return_value.generateIds.call_count,1)
    def test_corrupt_existing_fails_without_overwrite(self):
        drive=self.setup_drive()
        with self.assertRaises(RuntimeError):
            m.upload_archive(drive,"folder","month","hash",b"abc",
                Mock(return_value={"id":"old"}),Mock(side_effect=RuntimeError("mismatch")))
        drive.files.return_value.create.assert_not_called()
