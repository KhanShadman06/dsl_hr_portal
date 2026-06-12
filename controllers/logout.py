# -*- coding: utf-8 -*-

from urllib.parse import urlencode

from odoo import http
from odoo.addons.web.controllers.home import Home
from odoo.addons.web.controllers.session import Session
from odoo.addons.web.controllers.utils import ensure_db
from odoo.http import request


class DslHrPortalHome(Home):
    @http.route('/web/login', type='http', auth='none')
    def web_login(self, redirect=None, **kw):
        if request.httprequest.method == 'GET':
            ensure_db()
            query = {}
            if redirect:
                query['redirect'] = redirect
            target = '/dsl/login'
            if query:
                target = '%s?%s' % (target, urlencode(query))
            return request.redirect(target, 303)
        return super().web_login(redirect=redirect, **kw)


class DslHrPortalSession(Session):
    @http.route('/web/session/logout', type='http', auth='none')
    def logout(self, redirect='/dsl/login'):
        if redirect in (None, '', '/web', '/web/login'):
            redirect = '/dsl/login'
        return super().logout(redirect=redirect)
