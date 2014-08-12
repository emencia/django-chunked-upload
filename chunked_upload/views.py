
# Import from the Standard Library
import re

# Import from Django
from django.core.files.base import ContentFile
from django.utils import timezone

# Import from Django Rest Framework
from rest_framework.views import APIView

# Import from here
from .models import ChunkedUpload
from .response import Response
from .constants import COMPLETE, FAILED
from .exceptions import BadRequest, Gone


class ChunkedUploadBaseView(APIView):
    """
    Base view for the rest of chunked upload views.
    """

    # Has to be a ChunkedUpload subclass
    model = ChunkedUpload

    def get_queryset(self, request):
        """
        Get (and filter) ChunkedUpload queryset.
        By default, user can only continue uploading his own uploads.
        """
        return self.model.objects.filter(user=request.user)

    def get_upload(self, request, upload_id):
        queryset = self.get_queryset(request)
        try:
            return queryset.get(upload_id=upload_id)
        except self.model.DoesNotExist:
            return None

    def validate(self, request):
        """
        Placeholder method to define extra validation. Must raise
        APIException if validation fails.
        """

    def get_response_data(self, chunked_upload, request):
        """
        Data for the response. Should return a dictionary-like object.
        Called *only* if POST is successful.
        """
        return {}

    def pre_save(self, chunked_upload, request, new=False):
        """
        Placeholder method for calling before saving an object.
        May be used to set attributes on the object that are implicit
        in either the request, or the url.
        """

    def save(self, chunked_upload, request, new=False):
        """
        Method that calls save(). Overriding may be useful is save() needs
        special args or kwargs.
        """
        chunked_upload.save()

    def post_save(self, chunked_upload, request, new=False):
        """
        Placeholder method for calling after saving an object.
        """

    def _save(self, chunked_upload):
        """
        Wraps save() method.
        """
        new = chunked_upload.id is None
        self.pre_save(chunked_upload, self.request, new=new)
        self.save(chunked_upload, self.request, new=new)
        self.post_save(chunked_upload, self.request, new=new)



class ChunkedUploadView(ChunkedUploadBaseView):
    """
    Uploads large files in multiple chunks. Also, has the ability to resume
    if the upload is interrupted.
    """

    field_name = 'file'
    content_range_pattern = re.compile(r'^bytes (\d+)-(\d+)/(\d+)$')

    def get_extra_attrs(self, request):
        """
        Extra attribute values to be passed to the new ChunkedUpload instance.
        Should return a dictionary-like object.
        """
        return {}

    def create_chunked_upload(self, request, upload_id, chunk):
        """
        Creates new chunked upload instance. Called if no 'upload_id' is
        found in the POST data.
        """
        kw = {'upload_id': upload_id,
              'user': request.user,
              'filename': chunk.name}
        kw.update(self.get_extra_attrs(request))
        chunked_upload = self.model(**kw)
        # file starts empty
        chunked_upload.file.save(name='', content=ContentFile(''), save=False)
        return chunked_upload

    def is_valid_chunked_upload(self, chunked_upload):
        """
        Check if chunked upload has already expired or is already complete.
        """
        if chunked_upload.expired:
            raise Gone, 'Upload has expired'
        error_msg = 'Upload has already been marked as "%s"'
        if chunked_upload.status == COMPLETE:
            raise BadRequest, error_msg % 'complete'
        if chunked_upload.status == FAILED:
            raise BadRequest, error_msg % 'failed'

    def get_response_data(self, chunked_upload, request):
        """
        Data for the response. Should return a dictionary-like object.
        """
        return {
            'upload_id': chunked_upload.upload_id,
            'offset': chunked_upload.offset,
            'expires': chunked_upload.expires_on
        }

    def post(self, request, *args, **kwargs):
        # Check input data
        chunk = request.FILES.get(self.field_name)
        if chunk is None:
            raise BadRequest, 'No chunk file was submitted'

        upload_id = request.POST.get('md5')
        if upload_id is None:
            raise BadRequest, 'No md5 was submitted'

        content_range = request.META.get('HTTP_CONTENT_RANGE', None)
        if content_range is None:
            raise BadRequest, 'Missing Content-Range header'

        match = self.content_range_pattern.match(content_range)
        if match is None:
            raise BadRequest, 'Wrong Content-Range header "%s"' % content_range

        start, end, total = match.groups()
        start, end, total = int(start), int(end), int(total)

        self.validate(request)

        # Get or create the model
        chunked_upload = self.get_upload(request, upload_id)
        if chunked_upload:
            self.is_valid_chunked_upload(chunked_upload)
        else:
            chunked_upload = self.create_chunked_upload(request, upload_id, chunk)

        if chunked_upload.offset != start:
            if start == 0:
                chunked_upload.delete()
                chunked_upload = self.create_chunked_upload(request, upload_id, chunk)
            else:
                error = 'Offsets do not match "%s"'
                raise BadRequest, error % chunked_upload.offset

        # Save chunk
        chunk_size = end - start + 1
        chunked_upload.append_chunk(chunk, chunk_size=chunk_size, save=False)
        self._save(chunked_upload)

        # Case 1: upload is not complete
        if end < total:
            return Response(self.get_response_data(chunked_upload, request),
                            status=200)

        # Case 2: Upload is complete
        if chunked_upload.status == COMPLETE:
            return BadRequest, "Upload has already been marked as complete"

        self.md5_check(chunked_upload, upload_id)
        chunked_upload.status = COMPLETE
        chunked_upload.completed_on = timezone.now()
        self._save(chunked_upload)
        return self.on_completion(chunked_upload, request)


    def md5_check(self, chunked_upload, md5):
        """
        Verify if md5 checksum sent by client matches generated md5.
        """
        chunked_upload.file.open(mode='rb')  # mode = read+binary
        if chunked_upload.md5 != md5:
            chunked_upload.status = FAILED
            self._save(chunked_upload)
            raise BadRequest, 'md5 checksum does not match'


    def on_completion(self, chunked_upload, request):
        """
        Placeholder method to define what to do when upload is complete.
        """
        return Response(self.get_response_data(chunked_upload, request),
                        status=200)



class ChunkedUploadOffsetView(ChunkedUploadBaseView):

    def get(self, request, *args, **kw):
        upload_id = kw['md5']
        chunked_upload = self.get_upload(request, upload_id)
        offset = chunked_upload.offset if chunked_upload else 0
        return Response({'offset': offset}, status=200)
