import pytest

from inboxcleaner.core.gmail import GmailClient
from tests.fakes import FakeGmailClient, make_metadata


def test_fake_client_satisfies_protocol():
    fake: GmailClient = FakeGmailClient()  # type: ignore[assignment]
    assert fake is not None


@pytest.mark.asyncio
async def test_fake_records_calls():
    fake = FakeGmailClient(
        messages={"m1": make_metadata(msg_id="m1", from_="Uniqlo <news@uniqlo.com>")},
        query_ids={"category:promotions": ["m1"]},
    )
    ids = await fake.list_message_ids("category:promotions")
    assert ids == ["m1"]
    metas = await fake.batch_get_metadata(["m1"], ["From"])
    assert metas[0]["id"] == "m1"
    assert fake.calls[0] == ("list_message_ids", {"query": "category:promotions"})
