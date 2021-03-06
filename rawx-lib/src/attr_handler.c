/*
OpenIO SDS rawx-lib
Copyright (C) 2014 Worldine, original work as part of Redcurrant
Copyright (C) 2015 OpenIO, modified as part of OpenIO Software Defined Storage

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/

#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <fcntl.h>
#include <unistd.h>
#include <attr/xattr.h>

#include <metautils/lib/metautils.h>

#include "rawx.h"

static volatile ssize_t longest_xattr = 1024;
static volatile ssize_t longest_xattr_list = 2048;

static gchar *
_getxattr_from_fd(int fd, const char *attrname)
{
	ssize_t size;
	ssize_t s = longest_xattr;
	gchar *buf = g_malloc0(s);
retry:
	size = fgetxattr(fd, attrname, buf, s);
	if (size > 0)
		return buf;
	if (size == 0) {
		*buf = 0;
		return buf;
	}

	if (errno == ERANGE) {
		s = s*2;
		longest_xattr = 1 + MAX(longest_xattr, s);
		buf = g_realloc(buf, s);
		memset(buf, 0, s);
		goto retry;
	}

	int errsav = errno;
	g_free(buf);
	errno = errsav;
	return NULL;
}

/* -------------------------------------------------------------------------- */

#define SET(K,V) if (K) { \
	if ((V) && 0 > fsetxattr(fd, ATTR_DOMAIN "." K, V, strlen(V), 0)) \
		goto error_set_attr; \
}

gboolean
set_rawx_info_to_fd (int fd, GError **error, struct chunk_textinfo_s *cti)
{
	if (fd < 0) {
		GSETCODE(error, EINVAL, "invalid FD");
		return FALSE;
	}

	if (!cti)
		return TRUE;

	oio_str_upper(cti->container_id);
	oio_str_upper(cti->content_id);
	oio_str_upper(cti->chunk_hash);
	oio_str_upper(cti->metachunk_hash);

	SET(ATTR_NAME_CONTENT_CONTAINER, cti->container_id);

	SET(ATTR_NAME_CONTENT_ID,          cti->content_id);
	SET(ATTR_NAME_CONTENT_PATH,        cti->content_path);
	SET(ATTR_NAME_CONTENT_VERSION,     cti->content_version);
	SET(ATTR_NAME_CONTENT_SIZE,        cti->content_size);
	SET(ATTR_NAME_CONTENT_NBCHUNK,     cti->content_chunk_nb);

	SET(ATTR_NAME_CONTENT_STGPOL,      cti->content_storage_policy);
	SET(ATTR_NAME_CONTENT_CHUNKMETHOD, cti->content_chunk_method);
	SET(ATTR_NAME_CONTENT_MIMETYPE,    cti->content_mime_type);

	SET(ATTR_NAME_METACHUNK_SIZE, cti->metachunk_size);
	SET(ATTR_NAME_METACHUNK_HASH, cti->metachunk_hash);

	SET(ATTR_NAME_CHUNK_ID,   cti->chunk_id);
	SET(ATTR_NAME_CHUNK_SIZE, cti->chunk_size);
	SET(ATTR_NAME_CHUNK_HASH, cti->chunk_hash);
	SET(ATTR_NAME_CHUNK_POS,  cti->chunk_position);

	SET(ATTR_NAME_CHUNK_METADATA_COMPRESS, cti->compression_metadata);
	SET(ATTR_NAME_CHUNK_COMPRESSED_SIZE,   cti->compression_size);

	return TRUE;

error_set_attr:
	GSETCODE(error, errno, "setxattr error: (%d) %s", errno, strerror(errno));
	return FALSE;
}

gboolean
set_rawx_info_to_file (const char *p, GError **error, struct chunk_textinfo_s *cti)
{
	int fd = open(p, O_WRONLY);
	if (fd < 0) {
		GSETCODE(error, errno, "open() error: (%d) %s", errno, strerror(errno));
		return FALSE;
	} else {
		gboolean rc = set_rawx_info_to_fd (fd, error, cti);
		int errsav = errno;
		metautils_pclose (&fd);
		errno = errsav;
		return rc;
	}
}

gboolean
set_compression_info_in_attr(const char *p, GError ** error, const char *v)
{
	int rc = lsetxattr(p, ATTR_DOMAIN "." ATTR_NAME_CHUNK_METADATA_COMPRESS,
			v, strlen(v), 0);
	if (rc < 0)
		GSETCODE(error, errno, "setxattr error: (%d) %s", errno, strerror(errno));
	return rc == 0;
}

gboolean
set_chunk_compressed_size_in_attr(const char *p, GError ** error, guint32 v)
{
	gchar buf[32] = "";
	g_snprintf (buf, sizeof(buf), "%"G_GUINT32_FORMAT, v);
	int rc = lsetxattr(p, ATTR_DOMAIN ATTR_NAME_CHUNK_COMPRESSED_SIZE,
			buf, strlen(buf), 0);
	if (rc < 0)
		GSETCODE(error, errno, "setxattr error: (%d) %s", errno, strerror(errno));
	return rc == 0;
}

/* -------------------------------------------------------------------------- */

static gboolean
_get (int fd, const char *k, gchar **pv)
{
	gchar *v = _getxattr_from_fd (fd, k);
	int errsav = errno;
	oio_str_reuse(pv, v);
	errno = errsav;
	return v != NULL;
}

#define GET(K,R) _get(fd, ATTR_DOMAIN "." K, &(R))

gboolean
get_rawx_info_from_fd (int fd, GError **error, struct chunk_textinfo_s *cti)
{
	if (fd < 0) {
		GSETCODE(error, EINVAL, "invalid FD");
		return FALSE;
	}

	if (!cti) {
		gchar *v = NULL;
		if (!GET(ATTR_NAME_CONTENT_CONTAINER, v)) {
			if (errno == ENOTSUP) {
				GSETCODE(error, errno, "xatr not supported");
				return FALSE;
			}
		} else {
			g_free0 (v);
		}
		return TRUE;
	}

	if (!GET(ATTR_NAME_CONTENT_CONTAINER, cti->container_id)) {
		/* just one check to detect unsupported xattr */
		if (errno == ENOTSUP) {
			GSETCODE(error, errno, "xatr not supported");
			return FALSE;
		}
	}

	GET(ATTR_NAME_CONTENT_ID,      cti->content_id);
	GET(ATTR_NAME_CONTENT_PATH,    cti->content_path);
	GET(ATTR_NAME_CONTENT_VERSION, cti->content_version);
	GET(ATTR_NAME_CONTENT_SIZE,    cti->content_size);
	GET(ATTR_NAME_CONTENT_NBCHUNK, cti->content_chunk_nb);

	GET(ATTR_NAME_CONTENT_STGPOL,      cti->content_storage_policy);
	GET(ATTR_NAME_CONTENT_CHUNKMETHOD, cti->content_chunk_method);
	GET(ATTR_NAME_CONTENT_MIMETYPE,    cti->content_mime_type);

	GET(ATTR_NAME_METACHUNK_SIZE, cti->metachunk_size);
	GET(ATTR_NAME_METACHUNK_HASH, cti->metachunk_hash);

	GET(ATTR_NAME_CHUNK_ID,   cti->chunk_id);
	GET(ATTR_NAME_CHUNK_SIZE, cti->chunk_size);
	GET(ATTR_NAME_CHUNK_POS,  cti->chunk_position);
	GET(ATTR_NAME_CHUNK_HASH, cti->chunk_hash);

	GET(ATTR_NAME_CHUNK_METADATA_COMPRESS, cti->compression_metadata);
	GET(ATTR_NAME_CHUNK_COMPRESSED_SIZE,   cti->compression_size);

	return TRUE;
}

gboolean
get_rawx_info_from_file (const char *p, GError ** error, struct chunk_textinfo_s *cti)
{
	int fd = open(p, O_RDONLY);
	if (fd < 0) {
		GSETCODE(error, errno, "open() error: (%d) %s", errno, strerror(errno));
		return FALSE;
	} else {
		gboolean rc = get_rawx_info_from_fd (fd, error, cti);
		int errsav = errno;
		metautils_pclose (&fd);
		errno = errsav;
		return rc;
	}
}

gboolean
get_compression_info_in_attr(const char *p, GError ** error, GHashTable *table)
{
	EXTRA_ASSERT (p != NULL);
	EXTRA_ASSERT (table != NULL);

	gchar buf[2048];
	memset(buf, 0, sizeof(buf));

	int rc = lgetxattr(p, ATTR_DOMAIN "." ATTR_NAME_CHUNK_METADATA_COMPRESS, buf, sizeof(buf));
	if (rc < 0) {
		if (errno != ENOATTR) {
			GSETCODE(error, errno, "Failed to get compression attr: %s", strerror(errno));
			return FALSE;
		}
	} else {
		if (*buf) {
			GHashTable *ht = metadata_unpack_string(buf, NULL);
			metadata_merge (table, ht);
			g_hash_table_destroy (ht);
		}
	}

	return TRUE;
}

/* -------------------------------------------------------------------------- */

static void
_rawx_acl_clean(gpointer data, gpointer udata)
{
	(void) udata;
	addr_rule_g_free(data);
}

void
rawx_conf_gclean(rawx_conf_t* c)
{
	rawx_conf_clean(c);
	g_free(c);
}

void
rawx_conf_clean(rawx_conf_t* c)
{
	if(!c)
		return;

	if(c->ni) {
		namespace_info_free(c->ni);
		c->ni = NULL;
	}
	if(c->acl) {
		g_slist_foreach(c->acl, _rawx_acl_clean, NULL);
		g_slist_free(c->acl);
		c->acl = NULL;
	}
}

void
chunk_textinfo_free_content(struct chunk_textinfo_s *cti)
{
	if (!cti)
		return;
	oio_str_clean (&cti->container_id);

	oio_str_clean (&cti->content_id);
	oio_str_clean (&cti->content_path);
	oio_str_clean (&cti->content_version);
	oio_str_clean (&cti->content_size);
	oio_str_clean (&cti->content_chunk_nb);

	oio_str_clean (&cti->content_storage_policy);
	oio_str_clean (&cti->content_chunk_method);
	oio_str_clean (&cti->content_mime_type);

	oio_str_clean (&cti->metachunk_size);
	oio_str_clean (&cti->metachunk_hash);

	oio_str_clean (&cti->chunk_id);
	oio_str_clean (&cti->chunk_size);
	oio_str_clean (&cti->chunk_hash);
	oio_str_clean (&cti->chunk_position);

	oio_str_clean (&cti->compression_metadata);
	oio_str_clean (&cti->compression_size);
}
