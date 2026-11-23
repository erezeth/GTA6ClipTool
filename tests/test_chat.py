import threading

from core.chat import ChatWatcher, _read_from, parse_messages


def test_read_from_recovers_when_file_shrinks(tmp_path):
    path = tmp_path / "chat.live_chat.json.part"
    path.write_bytes(b"0123456789")
    chunk, offset = _read_from(path, 20)
    assert chunk == b"0123456789"
    assert offset == 10


def test_read_from_reads_only_new_bytes(tmp_path):
    path = tmp_path / "chat.live_chat.json.part"
    path.write_bytes(b"abcde")
    chunk, offset = _read_from(path, 2)
    assert chunk == b"cde"
    assert offset == 5


def test_chat_watcher_not_alive_before_start(tmp_path):
    watcher = ChatWatcher("https://example.com", tmp_path, lambda t: None,
                          threading.Event())
    assert watcher.alive() is False


def test_parse_messages_ignores_tickers_and_viewers():
    lines = [
        b'{"videoOffsetTimeMsec":"12000","replayChatItemAction":{"actions":[{"addChatItemAction":'
        b'{"item":{"liveChatTextMessageRenderer":{}}}}]}}',
        b'{"videoOffsetTimeMsec":"13000","replayChatItemAction":{"actions":[{"addLiveChatTickerItemAction":{}}]}}',
        b'{"videoOffsetTimeMsec":"14000","replayChatItemAction":{"actions":[{"addChatItemAction":'
        b'{"item":{"liveChatPaidMessageRenderer":{}}}}]}}',
        b'',
        b'not json',
    ]
    assert parse_messages(lines) == [12.0, 14.0]


def test_parse_messages_empty():
    assert parse_messages([]) == []


def test_parse_messages_replay_nested_offset():
    lines = [
        b'{"replayChatItemAction":{"videoOffsetTimeMsec":"12345000","actions":['
        b'{"addChatItemAction":{"item":{"liveChatTextMessageRenderer":{}}}}]}}',
        b'{"replayChatItemAction":{"videoOffsetTimeMsec":"isLive","actions":['
        b'{"addChatItemAction":{"item":{"liveChatTextMessageRenderer":{}}}}]}}',
    ]
    assert parse_messages(lines) == [12345.0]
