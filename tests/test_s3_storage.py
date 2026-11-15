import tempfile
import unittest
from pathlib import Path

from botocore.exceptions import ClientError

from nasa_explorer.storage.s3 import publish


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.buckets = set()

    def head_bucket(self, *, Bucket):
        if Bucket not in self.buckets:
            raise ClientError({"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadBucket")

    def create_bucket(self, *, Bucket):
        self.buckets.add(Bucket)

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadObject")
        return self.objects[(Bucket, Key)]

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):
        Body.read()
        self.objects[(Bucket, Key)] = {"Metadata": Metadata, "ContentLength": len(DATA)}


DATA = b"validated-cog-content"


class S3StorageTests(unittest.TestCase):
    def test_publish_uses_content_addressed_key_and_reuses_matching_object(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "asset.tif"
            source.write_bytes(DATA)
            s3 = FakeS3()
            first = publish(source, bucket="nisar-assets", s3=s3)
            second = publish(source, bucket="nisar-assets", s3=s3)
            self.assertEqual(first, second)
            self.assertIn(first["sha256"], first["key"])
            self.assertEqual(len(s3.objects), 1)


if __name__ == "__main__":
    unittest.main()
