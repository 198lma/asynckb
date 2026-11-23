# Modified for asynckb:
# independent distribution and KingbaseES compatibility.
# Copyright (C) 2016-present the asyncpg authors and contributors
# <see AUTHORS file>
#
# This module is part of asynckb and is released under
# the Apache 2.0 License: http://www.apache.org/licenses/LICENSE-2.0


cdef class PreparedStatementState:
    cdef:
        readonly str name
        readonly str query
        readonly bint closed
        readonly bint prepared
        readonly int refs
        readonly type record_class
        readonly bint ignore_custom_codec
        object parse_parameter_oids


        list         row_desc
        list         parameters_desc

        ConnectionSettings settings

        int16_t      args_num
        bint         have_text_args
        tuple        args_codecs

        int16_t      cols_num
        object       cols_desc
        bint         have_text_cols
        bint         use_row_desc_format
        tuple        rows_codecs

    cdef _encode_bind_msg(self, args, int seqno = ?)
    cpdef _init_codecs(self)
    cdef _ensure_rows_decoder(self)
    cdef _ensure_args_encoder(self)
    cdef _set_row_desc(self, object desc, bint exact_format = ?)
    cdef _set_args_desc(self, object desc)
    cdef _decode_row(self, const char* cbuf, ssize_t buf_len)
