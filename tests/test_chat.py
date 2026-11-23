from core.chat import parse_messages


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
