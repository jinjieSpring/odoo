# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

from . import models
from . import controllers

# Add post-init hook to assign default json file in firebase_key_file, as default=_get_firebase_records is not triggered when create new database.
def post_init_hook(env):
    company = env.company
    for rec in company:
        if not rec.firebase_key_file:
            rec.firebase_key_file = company._get_firebase_records()