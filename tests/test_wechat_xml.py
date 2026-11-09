from foxstar_bot.wechat_xml import normalize_wechat_content, wechat_appmsg_type, wechat_image_length, wechat_is_document_appmsg


QUOTE_XML = """<?xml version="1.0"?>
<msg>
  <appmsg appid="" sdkver="0">
    <title>请查询示例文档。

这是人为构造的引用消息。</title>
    <type>57</type>
    <refermsg>
      <type>1</type>
      <fromusr>900000001@chatroom</fromusr>
      <chatusr>wxid_example008</chatusr>
      <displayname>测试成员甲</displayname>
      <content>
请说明测试步骤</content>
    </refermsg>
  </appmsg>
</msg>"""


def test_normalize_wechat_quote_message():
    normalized = normalize_wechat_content(QUOTE_XML, 49)

    assert normalized.startswith("[引用消息]")
    assert "当前回复: 请查询示例文档。" in normalized
    assert "引用原文: 测试成员甲: 请说明测试步骤" in normalized
    assert "<refermsg>" not in normalized
    assert "<appmsg" not in normalized


def test_normalize_wechat_quote_of_image_message():
    content = """<?xml version="1.0"?>
<msg>
  <appmsg appid="" sdkver="0">
    <title>这个是什么图片</title>
    <type>57</type>
    <refermsg>
      <type>3</type>
      <displayname>Example User</displayname>
      <content>&lt;msg&gt;&lt;img cdnthumbwidth="576" cdnthumbheight="323" length="102657" /&gt;&lt;/msg&gt;</content>
    </refermsg>
  </appmsg>
</msg>"""

    normalized = normalize_wechat_content(content, 49)

    assert "当前回复: 这个是什么图片" in normalized
    assert "引用原文: Example User: [图片 576x323]" in normalized
    assert "<img" not in normalized


def test_normalize_wechat_emoji_message():
    assert normalize_wechat_content('<emoji fromusername="x" />', 47) == "[动画表情]"


def test_normalize_wechat_image_message():
    content = '<msg><img cdnthumbwidth="84" cdnthumbheight="180" /></msg>'

    assert normalize_wechat_content(content, 3) == "[图片 84x180]"


def test_malformed_xml_returns_original_content():
    content = "<msg><appmsg>"
    assert normalize_wechat_content(content, 49) == content


def test_wechat_appmsg_type_reads_quote_type():
    assert wechat_appmsg_type(QUOTE_XML) == "57"


def test_wechat_image_length_reads_image_length():
    assert wechat_image_length('<msg><img length="102657" /></msg>') == 102657


def test_normalize_wechat_share_card_does_not_leak_raw_xml():
    content = """<?xml version="1.0"?>
<msg>
  <appmsg appid="" sdkver="0">
    <title>腾讯投票</title>
    <des>今天吃什么</des>
    <type>5</type>
  </appmsg>
</msg>"""

    normalized = normalize_wechat_content(content, 49)

    assert normalized == "[分享] 腾讯投票 - 今天吃什么"
    assert "<appmsg" not in normalized


def test_wechat_is_document_appmsg_only_for_real_document_types():
    file_card = """<?xml version="1.0"?><msg><appmsg><title>paper.pdf</title><type>6</type></appmsg></msg>"""
    share_card = """<?xml version="1.0"?><msg><appmsg><title>腾讯投票</title><type>5</type></appmsg></msg>"""

    assert wechat_is_document_appmsg(file_card) is True
    assert wechat_is_document_appmsg(share_card) is False
