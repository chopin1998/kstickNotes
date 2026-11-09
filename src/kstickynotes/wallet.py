"""Talk to KDE Wallet on the session bus, without putting secrets in argv."""
from contextlib import contextmanager, suppress
import hashlib

from jeepney import DBusAddress, MessageType, new_method_call
from jeepney.io.blocking import open_dbus_connection


ADDRESS = DBusAddress('/modules/kwalletd6', bus_name='org.kde.kwalletd6',
                      interface='org.kde.KWallet')
APP_ID = 'KStickyNotes'
FOLDER = 'KStickyNotes'


class WalletError(RuntimeError):
    """A safe error that never includes replies containing credentials."""


def _call(bus, method, signature='', *arguments, timeout=10):
    message = new_method_call(ADDRESS, method, signature or None, arguments)
    try:
        reply = bus.send_and_get_reply(message, timeout=timeout)
    except TimeoutError:
        raise WalletError('KDE 钱包没有及时响应；请检查解锁或授权窗口后重试') from None
    except (OSError, EOFError, ValueError, RuntimeError):
        raise WalletError('与 KDE 钱包的连接中断，请重试') from None
    if reply.header.message_type != MessageType.method_return or len(reply.body) != 1:
        raise WalletError('KDE 钱包服务无法完成请求，请检查钱包是否启用')
    return reply.body[0]


@contextmanager
def _wallet():
    try:
        bus = open_dbus_connection(bus='SESSION', auth_timeout=5)
    except (OSError, EOFError, ValueError, RuntimeError):
        raise WalletError('无法连接桌面会话中的 KDE 钱包') from None
    with bus:
        if _call(bus, 'isEnabled') is not True:
            raise WalletError('KDE 钱包未启用或尚未就绪')
        name = _call(bus, 'networkWallet')
        if not isinstance(name, str) or not name:
            raise WalletError('未设置默认 KDE 钱包')
        handle = _call(bus, 'open', 'sxs', name, 0, APP_ID, timeout=120)
        if type(handle) is not int or handle < 0:
            raise WalletError('无法打开 KDE 钱包；请解锁并允许 KStickyNotes 访问')
        try:
            yield bus, handle
        finally:
            with suppress(WalletError):
                _call(bus, 'close', 'ibs', handle, False, APP_ID, timeout=3)


def wallet_password(url, username, password=None):
    key = 'webdav-' + hashlib.sha256((url + '\n' + username).encode()).hexdigest()
    with _wallet() as (bus, handle):
        entry = (handle, FOLDER, key)
        if password is not None:
            folder = (handle, FOLDER, APP_ID)
            if not _call(bus, 'hasFolder', 'iss', *folder):
                if not _call(bus, 'createFolder', 'iss', *folder):
                    raise WalletError('无法在 KDE 钱包中创建 KStickyNotes 文件夹')
            # Unlike kwallet-query 6.24, explicitly write a password even if
            # the key does not exist yet.
            if _call(bus, 'writePassword', 'issss', *entry, password, APP_ID) != 0:
                raise WalletError('KDE 钱包未保存应用密码，请检查钱包或访问权限')

        if not _call(bus, 'hasEntry', 'isss', *entry, APP_ID):
            if not _call(bus, 'isOpen', 'i', handle):
                raise WalletError('KDE 钱包已锁定，请解锁后重试')
            if password is not None:
                raise WalletError('KDE 钱包写入后找不到条目，本次同步未开始')
            raise WalletError('当前 KDE 钱包没有此账号的应用密码；请在「同步设置」中重新填写')

        secret = _call(bus, 'readPassword', 'isss', *entry, APP_ID)
        if not isinstance(secret, str) or not secret:
            raise WalletError('KDE 钱包中的应用密码为空或无法读取；请在「同步设置」中重新填写')
        if password is not None and secret != password:
            raise WalletError('KDE 钱包读回的应用密码不一致，本次同步未开始')
        return secret
