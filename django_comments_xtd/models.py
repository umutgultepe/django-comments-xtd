from myproject.utils import get_dictionary_with_cache_priority
from django.conf import settings
from django.contrib.comments.models import Comment
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import models, transaction
from django.db.models import F, Max, Min
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext, ugettext_lazy as _
from django.contrib.auth import get_user_model 
MAX_THREAD_LEVEL = getattr(settings, 'COMMENTS_XTD_MAX_THREAD_LEVEL', 0)
MAX_THREAD_LEVEL_BY_APP_MODEL = getattr(settings, 'COMMENTS_XTD_MAX_THREAD_LEVEL_BY_APP_MODEL', {})


def max_thread_level_for_content_type(content_type):
    app_model = "%s.%s" % (content_type.app_label, content_type.model)
    if app_model in MAX_THREAD_LEVEL_BY_APP_MODEL:
        return MAX_THREAD_LEVEL_BY_APP_MODEL[app_model]
    else:
        return MAX_THREAD_LEVEL


class MaxThreadLevelExceededException(Exception):
    def __init__(self, content_type=None):
        self.max_by_app = max_thread_level_for_content_type(content_type)

    def __str__(self):
        return ugettext("Can not post comments over the thread level %{max_thread_level}") % {"max_thread_level": self.max_by_app}


class XtdCommentManager(models.Manager):
    def for_app_models(self, *args):
        """Return XtdComments for pairs "app.model" given in args"""
        content_types = []
        for app_model in args:
            app, model = app_model.split(".")
            content_types.append(ContentType.objects.get(app_label=app, 
                                                         model=model))
        return self.for_content_types(content_types)

    def for_content_types(self, content_types):
        qs = self.get_query_set().filter(content_type__in=content_types).reverse()
        return qs


class XtdComment(Comment):
    thread_id = models.IntegerField(default=0, db_index=True)
    parent_id = models.IntegerField(default=0)
    level = models.SmallIntegerField(default=0)
    order = models.IntegerField(default=1, db_index=True)
    followup = models.BooleanField(help_text=_("Receive by email further comments in this conversation"), blank=True)
    objects = XtdCommentManager()

    class Meta:
        ordering = ('thread_id', 'order')

    def save(self, *args, **kwargs):
        is_new = self.pk == None
        super(Comment, self).save(*args, **kwargs)
        if is_new:
            if not self.parent_id:
                self.parent_id = self.id
                self.thread_id = self.id
            else:
                if max_thread_level_for_content_type(self.content_type):
                    with transaction.commit_on_success():
                        self._calculate_thread_data()
                else:
                    raise MaxThreadLevelExceededException(self.content_type)
            kwargs["force_insert"] = False
            super(Comment, self).save(*args, **kwargs)

    def _calculate_thread_data(self):
        # Implements the following approach:
        #  http://www.sqlteam.com/article/sql-for-threaded-discussion-forums        
        parent = XtdComment.objects.get(pk=self.parent_id)
        if parent.level == max_thread_level_for_content_type(self.content_type):
            raise MaxThreadLevelExceededException(self.content_type)

        self.thread_id = parent.thread_id
        self.level = parent.level + 1
        qc_eq_thread = XtdComment.objects.filter(thread_id = parent.thread_id)
        qc_ge_level = qc_eq_thread.filter(level__lte = parent.level,
                                          order__gt = parent.order)
        if qc_ge_level.count():
            min_order = qc_ge_level.aggregate(Min('order'))['order__min'] 
            XtdComment.objects.filter(thread_id = parent.thread_id,
                                      order__gte = min_order).update(order=F('order')+1)
            self.order = min_order
        else:
            max_order = qc_eq_thread.aggregate(Max('order'))['order__max']
            self.order = max_order + 1

    @models.permalink
    def get_reply_url(self):
        return ("comments-xtd-reply", None, {"cid": self.pk})

    def allow_thread(self):
        if self.level < max_thread_level_for_content_type(self.content_type):
            return True
        else:
            return False

    def get_item_new_comment_context(self):
        user = self.user
        item = self.content_object
        if item is None:
            return
        
        if self.content_object.__class__._meta.object_name == "Picture":
            item_type = 1
            url_item = 'picture'
        else:
            item_type = 2
            url_item = 'video'
    
        domain = 'eversnapapp.com'
        eversnap_url = getattr(settings, 'EVERSNAP_DOMAIN', 'http://eversnapapp.com')
        mwa_user = self.user
       
        content = {
            'userId': str(mwa_user.id),
            'itemType': str(item_type),
            'itemId': str(item.id),
            'thumbUrl': item.image_thumb.url if item_type == 1 else item.thumb,
            'userName': mwa_user.get_full_name() or 'someone',
            'albumTitle': item.album.title or '',
            'albumId': str(item.album.id),
            'ios_type': 'APNS_COMMENT_USER',
            'android_type': '12',
            'site_domain': domain,
            'url': eversnap_url + '/' + url_item + '/' + str(item.id),
        }
        return content
    
    get_item_new_comment_member_context = get_item_new_comment_context
        
    @classmethod
    def get_notification_context(cls, notification_type, instance=None, objects=[]):
        if instance is not None:
            obj = instance
        else:
            obj = objects[0]
        method_name = "get_%s_context" % notification_type
        context = getattr(obj, method_name)()
        if instance is not None:
            return context
        object_count = len(objects)
        mob_index = min(object_count, 4)
        context['ios_type'] = settings.MOB_TYPES[notification_type][mob_index]['ios']
        context['android_type'] = settings.MOB_TYPES[notification_type][mob_index]['android']
        if object_count > 1:
            user = objects[1].user
            context["userName2"] = context["userName"]
            context["userName"] = (user.firstName or '') + (' ' + user.lastName if user.lastName else '')
            context["thumbUrl"] = getattr(objects[-1], method_name)()["thumbUrl"]
        else:
            return context
        if object_count == 2:
            return context
        elif object_count == 3:
            user = objects[2].user
            context["userName3"] = context["userName2"]
            context["userName2"] = context["userName"]
            context["userName"] = (user.firstName or '') + (' ' + user.lastName if user.lastName else '')
        else:
            user = objects[-2].user
            context["userName2"] = (user.firstName or '') + (' ' + user.lastName if user.lastName else '')
            user = objects[-1].user
            context["userName"] = (user.firstName or '') + (' ' + user.lastName if user.lastName else '')
            context["totalUsers"] = object_count - 1
        return context

    def get_user_status(self, user, privacy, album_owner_id):
        status = "user"
        if user.id == settings.ANONYMOUS_USER_ID or user is None:
            status = "guest"
        elif album_owner_id == user.id or user.id == self.user_id:
            status = "owner"
        # One query here
        elif JoinMember.objects.filter(user_id=user.id, album_id=self.album_id, active=True).exists():
            status = "member"
        return status

    def get_like_list(self, user, skip_permission_check=False):
        from myproject.like.models import Like
        """
        Get a list of likes for this comment. If the user has no read permission, get None.
        @user: The user whose point of view will be used when fetching likes.
        @skip_permission_check: If you already checked the permissions, set this to True in order
        to avoid a redundant database call.
        
        This method builds the like list manually, meaning likes themselves are not cached. Therefore
        there might be a lot of cache calls in this method. Change it if it effects performance.
        """
        if not skip_permission_check:
            item_cache_key = "_%s_dict_%s_" % (self.content_type.model_class().item_name, "%s")
            object_dict = get_dictionary_with_cache_priority(
                item_cache_key,
                self.content_type.model_class(),
                self.object_pk,
                "get_short_dict"
            )
            album_dict = get_dictionary_with_cache_priority(
                "_album_dict_%d_",
                "mwa.Album",
                object_dict["album_id"],
                "get_short_dict"
            )
            privacy = album_dict.pop("privacy")
            # If the user is not the owner or anonymous, this method launches a query
            status = self.get_user_status(user, privacy, album_dict["owner_id"])
            if privacy[status] & settings.PERMISSIONS["read"] == 0:
                # User cannot read this item, return None
                return False
        # one query here
        likes = Like.objects.filter(
            resource_type=3,
            resource_id=self.pk,
        ).only("id", "user")
        item_dict = {
            "type": 3,
            "id": self.id,
            "owner_id": self.user_id
        }
        like_list = []
        for l in likes:
            liker_dict = get_dictionary_with_cache_priority(
                "_user_%d_owner_dict_",
                get_user_model(),
                l.user_id,
                "get_owner_dict",
                expected_field_list=["first_name", "last_name"]
            )
            t_dict = {
                "user": liker_dict,
                "item": item_dict,
                "id": l.id,
                "can_delete": user.id == l.user_id
            }
            like_list.append(t_dict)
        return like_list
        

    def get_owner_dict(self, update=False):
        """ Get a small dictionary with information of this comment's owner. Uses and sets
        _user_<user_id>_owner_dict_. """
        if not update:  # Try to get from cache first, without hitting database
            d = cache.get("_user_%d_owner_dict_" % self.user_id)
            if d is not None and "first_name" in d:
                return d
        return self.user.get_owner_dict(True)

    def get_likes_count(self, update=False):
        """ Get the number of likes for this comment, with priority on cache"""
        key_name = "_num_likes_for_comment_%d_" % self.pk
        if not update:
            n = cache.get(key_name)
            if n is not None:
                return n
        from myproject.like.models import Like
        n = Like.objects.filter(resource_type=3, resource_id=self.pk).count()
        cache.set(key_name, n)
        return n    
    
    def build_short_dict(self):
        """ Build the short dict. If everything is working, this method should not make a single
        database call."""
        item_cache_key = "_%s_dict_%s_" % (self.content_type.model_class().item_name, "%s")
        object_dict = get_dictionary_with_cache_priority(
            item_cache_key,
            self.content_type.model_class(),
            self.object_pk,
            "get_short_dict"
        )
        album_cache_key = "_album_dict_%s_"
        album_dict = get_dictionary_with_cache_priority(
            album_cache_key,
            "mwa.Album",
            object_dict["album_id"],
            "get_short_dict"
        )
        return {
            "comment": self.comment,
            "id": self.id,
            "likes_count": self.get_likes_count(),
            "object": {
                "id": self.object_pk,
                "type": self.content_type.model_class().item_type,
                "owner_id": object_dict["owner_id"]
            },
            "submit_date": self.submit_date.isoformat(),
            "user": self.get_owner_dict(),
            "album": {
                "id": album_dict["id"],
                "owner_id": album_dict["owner_id"],
            }
        }

    def get_short_dict(self, update=False):
        """ Get the short dict for this comment with key fields, priority on cache"""
        key_name = "_comment_dict_%d_" % self.pk
        if not update:
            d = cache.get(key_name)
            if d is not None:
                return d
        d = self.build_short_dict()
        cache.set(key_name, d)
        return d
    
    def get_long_dict(self, user):
        base_dict = self.get_short_dict()
        who_can_delete = [
            unicode(base_dict["user"]["id"]),
            unicode(base_dict["object"]["owner_id"]),
            unicode(base_dict["album"]["owner_id"]),
        ]
        base_dict["can_delete"] = unicode(user.id) in who_can_delete
        return base_dict

class DummyDefaultManager:
    """
    Dummy Manager to mock django's CommentForm.check_for_duplicate method.
    """
    def __getattr__(self, name):
        return lambda *args, **kwargs: []
    
    def using(self, *args, **kwargs):
        return self

    # def __repr__(self):
    #     return ""


class TmpXtdComment(dict):
    """
    Temporary XtdComment to be pickled, ziped and appended to a URL.
    """
    _default_manager = DummyDefaultManager()

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            return None

    def __setattr__(self, key, value):
        self[key] = value
            
    def save(self, *args, **kwargs):
        pass

    def _get_pk_val(self):
        if self.xtd_comment:
            return self.xtd_comment._get_pk_val()
        else:
            return ""

    def __reduce__(self):
        return (TmpXtdComment, (), None, None, self.iteritems())
