import unittest


def suite():
    from django_comments_xtd.tests import forms, models, templatetags, templatetags_views, views

    testsuite = unittest.TestSuite([
        unittest.TestLoader().loadTestsFromModule(models),
        unittest.TestLoader().loadTestsFromModule(forms),
        unittest.TestLoader().loadTestsFromModule(views),
        unittest.TestLoader().loadTestsFromModule(templatetags),
        unittest.TestLoader().loadTestsFromModule(templatetags_views),
    ])
    return testsuite
