from optparse import make_option

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.translation import ugettext as _

from chunked_upload.settings import EXPIRATION_DELTA
from chunked_upload.models import ChunkedUpload

prompt_msg = _(u'Do you want to delete {obj}?')


class Command(BaseCommand):

    # Has to be a ChunkedUpload subclass
    model = ChunkedUpload

    help = 'Deletes chunked uploads that have already expired.'

    option_list = BaseCommand.option_list + (
        make_option('--pretend',
                    action='store_true',
                    dest='pretend',
                    default=False,
                    help='Do not remove anything, just tell how many would be removed.'),
    )

    def handle(self, *args, **options):
        pretend = options.get('pretend')

        qs = self.model.objects.all()
        total = qs.count()

        qs = qs.filter(created_on__lt=(timezone.now() - EXPIRATION_DELTA))
        if pretend:
            print 'Called with --pretend option, nothing done, just pretending'
            n = qs.count()
        else:
            n = qs.delete()

        print '%d expired uplads deleted, of %d total uploads' % (n, total)
