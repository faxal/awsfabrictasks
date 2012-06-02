from boto.s3.key import Key
from fabric.api import task, abort
from fabric.contrib.console import confirm
from os import linesep
from os.path import exists

from awsfabrictasks.conf import awsfab_settings
from awsfabrictasks.utils import force_slashend
from awsfabrictasks.utils import parse_bool
from .api import S3ConnectionWrapper
from .api import iter_bucketcontents
from .api import S3File
from .api import S3FileExistsError
from .api import compute_localfile_md5sum


@task
def s3_ls(bucketname, prefix='', search=None, match=None, style='compact',
          delimiter=awsfab_settings.S3_DELIMITER):
    """
    List all items with the given prefix within the given bucket.

    :param bucketname: Name of an S3 bucket.
    :param prefix:
        The prefix to list. Defaults to empty string, which lists
        all items in the root directory.
    :param search:
        Search for keys whose name contains this string.
        Shortcut for ``match="*<search>*"``.
    :param match:
        A Unix shell style pattern to match. Matches against the entire key
        name (in filesystem terms: the absolute path).

        Ignored if ``search`` is provided.  Uses the ``fnmatch`` python module.
        The match is case-sensitive.

        Examples::

            *.jpg
            *2012*example*.log
            icon-*.png

    :param style:
        The style of the output. One of:

            - compact
            - verbose
            - nameonly

    :param delimiter:
        The delimiter to use. Defaults to ``awsfab_settings.S3_DELIMITER``.
    """
    bucket = S3ConnectionWrapper.get_bucket_using_pattern(bucketname)

    styles = ('compact', 'verbose', 'nameonly')
    if not style in styles:
        abort('Invalid style: {0}. Use one of {1}'.format(style, ','.join(styles)))
    if style == 'compact':
        formatstring = '{name:<70} {size:<10} {last_modified:<25} {mode}'
        print formatstring.format(name='NAME', size='SIZE', last_modified='LAST MODIFIED',
                                  mode='MODE')
    elif style == 'verbose':
        formatstring = '{linesep}'.join(('name: {name}',
                                         '    size: {size}',
                                         '    last_modified: {last_modified}',
                                         '    mode: {mode}'))
    elif style == 'nameonly':
        formatstring = '{name}'

    if search:
        match = '*{0}*'.format(search)

    formatter = lambda key: formatstring.format(linesep=linesep, **key.__dict__)
    for line in iter_bucketcontents(bucket, prefix=prefix, match=match,
                                    delimiter=delimiter, formatter=formatter):
        print line

@task
def s3_listbuckets():
    """
    List all S3 buckets.
    """
    connectionwrapper = S3ConnectionWrapper.get_connection()
    for bucket in connectionwrapper.connection.get_all_buckets():
        loggingstatus = bucket.get_logging_status()
        print '{0}:'.format(bucket.name)
        print '   location:', bucket.get_location()
        print '   loggingstatus:'
        print '      enabled:', loggingstatus.target != None
        print '      prefix:', loggingstatus.prefix
        print '      grants:', loggingstatus.grants


@task
def s3_createfile(bucketname, keyname, contents, overwrite=False):
    """
    Create a file with the given keyname and contents.

    :param bucketname: Name of an S3 bucket.
    :param keyname: The key to create/overwrite (In filesystem terms: absolute file path).
    :param contents: The data to put in the bucket.
    :param overwrite: Overwrite if exists? Defaults to ``False``.
    """
    bucket = S3ConnectionWrapper.get_bucket_using_pattern(bucketname)
    s3file = S3File(bucket, keyname)
    try:
        s3file.set_contents_from_string(contents, overwrite)
    except S3FileExistsError, e:
        abort(str(e))


@task
def s3_uploadfile(bucketname, keyname, localfile, overwrite=False):
    """
    Upload a local file.

    :param bucketname: Name of an S3 bucket.
    :param keyname: The key to create/overwrite (In filesystem terms: absolute file path).
    :param localfile: The local file to upload.
    :param overwrite: Overwrite if exists? Defaults to ``False``.
    """
    bucket = S3ConnectionWrapper.get_bucket_using_pattern(bucketname)
    s3file = S3File(bucket, keyname)
    try:
        s3file.set_contents_from_filename(localfile, overwrite)
    except S3FileExistsError, e:
        abort(str(e))

@task
def s3_printfile(bucketname, keyname):
    """
    Print the contents of the given key/file to stdout.

    :param bucketname: Name of an S3 bucket.
    :param keyname: The key to print (In filesystem terms: absolute file path).
    """
    bucket = S3ConnectionWrapper.get_bucket_using_pattern(bucketname)
    s3file = S3File(bucket, keyname)
    print s3file.get_contents_as_string()

@task
def s3_downloadfile(bucketname, keyname, localfile, overwrite=False):
    """
    Print the contents of the given key/file to stdout.

    :param bucketname: Name of an S3 bucket.
    :param keyname: The key to download (In filesystem terms: absolute file path).
    :param localfile: The local file to write the data to.
    :param overwrite: Overwrite local file if exists? Defaults to ``False``.
    """
    if exists(localfile) and not overwrite:
        abort('Local file exists: {0}'.format(localfile))
    bucket = S3ConnectionWrapper.get_bucket_using_pattern(bucketname)
    s3file = S3File(bucket, keyname)
    print s3file.get_contents_to_filename()

@task
def s3_delete(bucketname, keyname, noconfirm=False):
    """
    Remove a "file" from the given bucket.

    :param bucketname: Name of an S3 bucket.
    :param keyname: The key to remove (In filesystem terms: absolute file path).
    :param noconfirm:
        If this is ``True``, we will not ask for confirmation before
        removing the key. Defaults to ``False``.
    """
    bucket = S3ConnectionWrapper.get_bucket_using_pattern(bucketname)
    s3file = S3File(bucket, keyname)
    if not parse_bool(noconfirm):
        if not confirm('Remove {0}?'.format(keyname)):
            abort('Aborted')
    s3file.delete()


@task
def s3_same_file(bucketname, keyname, localfile):
    """
    Check if the ``keyname`` in the given ``bucketname`` has the same md5sum as
    the given ``localfile``. Files with the same md5sum are extremely likely to
    have the same contents. Prints ``True`` or ``False``.
    """
    bucket = S3ConnectionWrapper.get_bucket_using_pattern(bucketname)
    s3file = S3File(bucket, keyname, head=True)
    print s3file.etag_matches_localfile(localfile)


@task
def s3_upload_dir(bucketname, local_dir, remote_dir):
    """
    :param bucketname: Name of an S3 bucket.
    """
    bucket = S3ConnectionWrapper.get_bucket_using_pattern(bucketname)
    remote_dir = force_slashend(remote_dir)
    currentfiles = list(bucket.list(prefix=remote_dir))
    print currentfiles
    """
    from mimetypes import guess_type
    guess_type(filemeta.filename)[0]
    """
