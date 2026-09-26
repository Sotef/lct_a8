# -*- coding: utf-8 -*-
"""LDAP/AD-адаптер (read-only). MVP — локальная имитация (SERVICE_PLAN §2).

Контракт: `authenticate(username, password) -> dict | None`; при готовности
AD/LDAP реализуется bind по TLS 1.2+, результат мапится в поля User.
"""
from __future__ import annotations


class LdapAdapter:
    name = "ldap_ad"
    primary_key = "username"

    def __init__(self, url: str | None = None, bind_dn: str | None = None,
                 base_dn: str | None = None, use_tls: bool = True):
        self.url = url
        self.bind_dn = bind_dn
        self.base_dn = base_dn
        self.use_tls = use_tls

    def authenticate(self, username: str, password: str) -> dict | None:
        """Имитация: полномочность определяется в БД (локальные пользователи).

        Реальная интеграция (ldap3): read-only bind + поиск роли/района.
        """
        return None

    def search_groups(self, username: str) -> list[str]:
        return []