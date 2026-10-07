# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class IrModel(models.Model):
    _inherit = "ir.model"

    @api.model
    def has_searchable_parent_relation(self, model_names):
        """Return dict {model_name: bool} for each requested model"""

        res = {}
        for model_name in model_names:
            model = self.env.get(model_name)
            if not model:
                res[model_name] = False
                continue

            # check read access
            try:
                model.check_access_rights("read")
            except Exception:
                res[model_name] = False
                continue

            res[model_name] = bool(
                model._parent_store and model._parent_name in model._fields)

        return res
