use bytes::{Buf, Bytes};
use std::io;
use super::messages::*;

/// Decoder for pgoutput binary protocol
pub struct PgOutputDecoder {
    // Cache for relation schemas
    relations: std::collections::HashMap<u32, RelationMessage>,
}

impl PgOutputDecoder {
    pub fn new() -> Self {
        Self {
            relations: std::collections::HashMap::new(),
        }
    }
    
    /// Decode a pgoutput message from bytes
    pub fn decode(&mut self, mut data: Bytes) -> Result<PgOutputMessage, io::Error> {
        if data.is_empty() {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "Empty message"));
        }
        
        let msg_type = data.get_u8() as char;
        
        match msg_type {
            'B' => self.decode_begin(data),
            'C' => self.decode_commit(data),
            'R' => self.decode_relation(data),
            'I' => self.decode_insert(data),
            'U' => self.decode_update(data),
            'D' => self.decode_delete(data),
            'T' => self.decode_truncate(data),
            'Y' => self.decode_type(data),
            'O' => self.decode_origin(data),
            'M' => self.decode_message(data),
            _ => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("Unknown message type: {}", msg_type),
            )),
        }
    }
    
    fn decode_begin(&self, mut data: Bytes) -> Result<PgOutputMessage, io::Error> {
        let final_lsn = data.get_u64();
        let timestamp = data.get_i64();
        let xid = data.get_u32();
        
        Ok(PgOutputMessage::Begin(BeginMessage {
            final_lsn,
            timestamp,
            xid,
        }))
    }
    
    fn decode_commit(&self, mut data: Bytes) -> Result<PgOutputMessage, io::Error> {
        let flags = data.get_u8();
        let commit_lsn = data.get_u64();
        let end_lsn = data.get_u64();
        let timestamp = data.get_i64();
        
        Ok(PgOutputMessage::Commit(CommitMessage {
            flags,
            commit_lsn,
            end_lsn,
            timestamp,
        }))
    }
    
    fn decode_relation(&mut self, mut data: Bytes) -> Result<PgOutputMessage, io::Error> {
        let rel_id = data.get_u32();
        let namespace = read_cstring(&mut data)?;
        let name = read_cstring(&mut data)?;
        let replica_identity = data.get_u8();
        let n_columns = data.get_u16();
        
        let mut columns = Vec::new();
        for _ in 0..n_columns {
            let flags = data.get_u8();
            let col_name = read_cstring(&mut data)?;
            let type_id = data.get_u32();
            let type_modifier = data.get_i32();
            
            columns.push(ColumnInfo {
                flags,
                name: col_name,
                type_id,
                type_modifier,
            });
        }
        
        let relation = RelationMessage {
            rel_id,
            namespace,
            name,
            replica_identity,
            columns,
        };
        
        // Cache the relation
        self.relations.insert(rel_id, relation.clone());
        
        Ok(PgOutputMessage::Relation(relation))
    }
    
    fn decode_insert(&self, mut data: Bytes) -> Result<PgOutputMessage, io::Error> {
        let rel_id = data.get_u32();
        let tuple_type = data.get_u8();
        
        if tuple_type != b'N' {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("Expected new tuple (N), got: {}", tuple_type as char),
            ));
        }
        
        let tuple = read_tuple_data(&mut data)?;
        
        Ok(PgOutputMessage::Insert(InsertMessage { rel_id, tuple }))
    }
    
    fn decode_update(&self, mut data: Bytes) -> Result<PgOutputMessage, io::Error> {
        let rel_id = data.get_u32();
        let tuple_type = data.get_u8();
        
        let old_tuple = match tuple_type {
            b'O' | b'K' => {
                let old = read_tuple_data(&mut data)?;
                data.get_u8(); // consume 'N' for new tuple
                Some(old)
            }
            b'N' => None,
            _ => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("Unexpected tuple type: {}", tuple_type as char),
                ))
            }
        };
        
        let new_tuple = read_tuple_data(&mut data)?;
        
        Ok(PgOutputMessage::Update(UpdateMessage {
            rel_id,
            old_tuple,
            new_tuple,
        }))
    }
    
    fn decode_delete(&self, mut data: Bytes) -> Result<PgOutputMessage, io::Error> {
        let rel_id = data.get_u32();
        let tuple_type = data.get_u8();
        
        if tuple_type != b'O' && tuple_type != b'K' {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("Expected old tuple (O/K), got: {}", tuple_type as char),
            ));
        }
        
        let old_tuple = read_tuple_data(&mut data)?;
        
        Ok(PgOutputMessage::Delete(DeleteMessage { rel_id, old_tuple }))
    }
    
    fn decode_truncate(&self, mut data: Bytes) -> Result<PgOutputMessage, io::Error> {
        let n_relations = data.get_u32();
        let options = data.get_u8();
        
        let mut rel_ids = Vec::new();
        for _ in 0..n_relations {
            rel_ids.push(data.get_u32());
        }
        
        Ok(PgOutputMessage::Truncate(TruncateMessage { options, rel_ids }))
    }
    
    fn decode_type(&self, mut data: Bytes) -> Result<PgOutputMessage, io::Error> {
        let type_id = data.get_u32();
        let namespace = read_cstring(&mut data)?;
        let name = read_cstring(&mut data)?;
        
        Ok(PgOutputMessage::Type(TypeMessage {
            type_id,
            namespace,
            name,
        }))
    }
    
    fn decode_origin(&self, mut data: Bytes) -> Result<PgOutputMessage, io::Error> {
        let lsn = data.get_u64();
        let name = read_cstring(&mut data)?;
        
        Ok(PgOutputMessage::Origin(OriginMessage { lsn, name }))
    }
    
    fn decode_message(&self, mut data: Bytes) -> Result<PgOutputMessage, io::Error> {
        let flags = data.get_u8();
        let transactional = (flags & 1) != 0;
        let lsn = data.get_u64();
        let prefix = read_cstring(&mut data)?;
        let content_len = data.get_u32() as usize;
        
        let mut content = vec![0u8; content_len];
        data.copy_to_slice(&mut content);
        
        Ok(PgOutputMessage::Message(LogicalMessage {
            transactional,
            lsn,
            prefix,
            content,
        }))
    }
    
    pub fn get_relation(&self, rel_id: u32) -> Option<&RelationMessage> {
        self.relations.get(&rel_id)
    }
}

/// Read a null-terminated C string from bytes
fn read_cstring(data: &mut Bytes) -> Result<String, io::Error> {
    let mut bytes = Vec::new();
    loop {
        if data.is_empty() {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "Unexpected end of data while reading string",
            ));
        }
        let byte = data.get_u8();
        if byte == 0 {
            break;
        }
        bytes.push(byte);
    }
    String::from_utf8(bytes)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))
}

/// Read tuple data (column values) from bytes
fn read_tuple_data(data: &mut Bytes) -> Result<Vec<Option<Vec<u8>>>, io::Error> {
    let n_columns = data.get_u16();
    let mut tuple = Vec::new();
    
    for _ in 0..n_columns {
        let value_type = data.get_u8() as char;
        
        let value = match value_type {
            'n' => None, // NULL
            'u' => None, // UNCHANGED TOAST
            't' => {
                // Text/binary data
                let len = data.get_u32() as usize;
                let mut bytes = vec![0u8; len];
                data.copy_to_slice(&mut bytes);
                Some(bytes)
            }
            _ => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("Unknown tuple value type: {}", value_type),
                ))
            }
        };
        
        tuple.push(value);
    }
    
    Ok(tuple)
}
