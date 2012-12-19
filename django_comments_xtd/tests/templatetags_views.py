from django.core.urlresolvers import reverse
from django.contrib.comments.models import Comment
from django.contrib.sites.models import Site
from django.test import TestCase

from django_comments_xtd.tests.models import Article
from django_comments_xtd.models import XtdComment


class TemplatetagViewsTestCase(TestCase):
    def test_render_last_xtdcomments(self):
        article = Article.objects.create()

        XtdComment.objects.create(content_object=article, site_id=1, comment="Hi", submit_date="2012-12-12")

        response = self.client.get(reverse(
            "last-xtdcomments", 
            kwargs={'id': 5, 'app_model': 'tests.article'})
        )

        expected_html = '''<div id="c1" style="width:600px; padding: 5px 0; border-top: 1px solid #ddd">
        <div style="display:inline-block; width:400px"><div style="font-size:0.7em">Comment for: <a href=""></a>
        </div><p>Hi</p></div><div style="display:inline-block; width:180px; padding: 0 5px; background:#eee">
        <a href="/comments/cr/10/1/#c1">permalink</a><br/><span>12/12/2012</span><br/><em></em></div></div>
        '''

        self.assertHTMLEqual(expected_html, response.content)
