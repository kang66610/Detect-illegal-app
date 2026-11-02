from agent.ai_explorer.login_session import ManualConsentCodeProbe
from agent.ai_explorer.page_state import parse_page


def test_manual_consent_code_probe_observes_request_after_unchecked_terms():
    before = parse_page(
        ".LoginActivity",
        '''<hierarchy>
          <node text="登录即表示已阅读并同意《用户协议》和《隐私政策》" clickable="false"/>
          <node resource-id="com.demo:id/agree" checkable="true" checked="false" clickable="true" class="android.widget.CheckBox"/>
          <node text="获取验证码" resource-id="com.demo:id/send_code" clickable="true" enabled="true" class="android.widget.TextView"/>
        </hierarchy>''',
    )
    after = parse_page(
        ".LoginActivity",
        '''<hierarchy>
          <node text="登录即表示已阅读并同意《用户协议》和《隐私政策》" clickable="false"/>
          <node resource-id="com.demo:id/agree" checkable="true" checked="false" clickable="true" class="android.widget.CheckBox"/>
          <node text="59s" resource-id="com.demo:id/send_code" clickable="true" enabled="false" class="android.widget.TextView"/>
        </hierarchy>''',
    )

    probe = ManualConsentCodeProbe()
    armed = probe.snapshot(before.elements)
    triggered = probe.snapshot(after.elements)

    assert armed is not None and armed.armable
    assert triggered is not None
    assert triggered.request_accepted_after(armed)


def test_manual_consent_code_probe_supports_custom_image_checkbox():
    page = parse_page(
        ".LoginActivity",
        '''<hierarchy>
          <node text="登录即表示同意《用户协议》和《隐私政策》" clickable="false"/>
          <node resource-id="com.demo:id/iv_agree_check" checked="false" clickable="true" class="android.widget.ImageView"/>
          <node text="重新获取验证码" resource-id="com.demo:id/tv_send_code" clickable="true" enabled="true" class="android.widget.TextView"/>
        </hierarchy>''',
    )

    snapshot = ManualConsentCodeProbe().snapshot(page.elements)

    assert snapshot is not None
    assert snapshot.armable
