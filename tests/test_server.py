import unittest
from unittest.mock import patch

import server


class ServerEntrypointTests(unittest.TestCase):
    def test_server_parser_reads_host_and_port(self):
        parser = server.build_parser()

        args = parser.parse_args(["--host", "127.0.0.1", "--port", "5050"])

        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 5050)

    def test_server_parser_uses_environment_defaults(self):
        with patch.dict(
            "os.environ",
            {
                "ADB_AUTOMATION_API_HOST": "127.0.0.1",
                "ADB_AUTOMATION_API_PORT": "5051",
            },
        ):
            parser = server.build_parser()

        args = parser.parse_args([])

        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 5051)


if __name__ == "__main__":
    unittest.main()
