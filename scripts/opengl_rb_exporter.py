import struct
import os
import renderdoc as rd

# Destination folder
output_dir = "./exported_meshes"
os.makedirs(output_dir, exist_ok=True)

def export_all_indexed_drawcalls_to_obj(controller):
    root_actions = controller.GetRootActions()
    draw_elements_actions = []

    # 1. Collect names of all resources
    resources = controller.GetResources()
    resource_names = {}
    for res in resources:
        resource_names[res.resourceId] = res.name

    # 2. Collect actions (glDrawElements)
    def collect_draw_elements(action_list):
        for act in action_list:
            is_draw = act.flags & rd.ActionFlags.Drawcall
            is_indexed = act.flags & rd.ActionFlags.Indexed
            
            if is_draw and is_indexed:
                draw_elements_actions.append(act)
                
            if act.children:
                collect_draw_elements(act.children)

    collect_draw_elements(root_actions)
    
    print(f"\n{len(draw_elements_actions)} indexed actions for export have been found")

    # 3. Iterate over all EID
    for action in draw_elements_actions:
        target_eid = action.eventId
        
        # Move frame to the new drawcall
        controller.SetFrameEvent(target_eid, True)
        gl_pipe = controller.GetGLPipelineState()
        v_input = gl_pipe.vertexInput
        
        # Check if there is no attributes
        if not v_input.attributes or not v_input.vertexBuffers:
            continue
            
        attr_index = 0  # POSITION0 by default 
        
        vertex_attr = v_input.attributes[attr_index]
        element_offset = vertex_attr.byteOffset 
        bind_slot = getattr(vertex_attr, 'vertexBufferSlot', 0)    # Get the slot number
        
        if bind_slot >= len(v_input.vertexBuffers):
            continue
            
        # Get the vertex buffer information
        vertex_binding = v_input.vertexBuffers[bind_slot]
        vertex_buffer_id = vertex_binding.resourceId       # Unique buffer ID in memory
        stride = vertex_binding.byteStride                 # Vertex size in bytes
        vb_offset = vertex_binding.byteOffset              # Where the model data begins in buffer
        
        if vertex_buffer_id == rd.ResourceId.Null() or stride == 0:
            continue
    
        # Get the readable file name 
        buffer_name = resource_names.get(vertex_buffer_id, f"buffer_{target_eid}")
        clean_buffer_name = "".join([c if c.isalnum() or c in "@_-" else "_" for c in buffer_name])

        # 4. Read index buffer
        ib_id = v_input.indexBuffer                   # ID of buffer with indices
        ib_offset = getattr(action, 'indexOffset', 0) # From which byte necessary indices begin
        idx_stride = v_input.indexByteStride          # Index size in bytes
        num_indices = action.numIndices               # How many indices do the model have
        
        if ib_id == rd.ResourceId.Null() or num_indices == 0:
            continue

        # Get the indices    
        ib_bytes = controller.GetBufferData(ib_id, ib_offset, idx_stride * num_indices)
        fmt = f"{num_indices}H" if idx_stride == 2 else f"{num_indices}I"
        indices = list(struct.unpack_from(fmt, ib_bytes, 0))

        if not indices:
            continue

        # 5. Get coordinates
        max_idx = max(indices)    # Number of unique indices - 1 s
        buffer_bytes = controller.GetBufferData(vertex_buffer_id, vb_offset, stride * (max_idx+ 1))
        
        vertices = {}
        for idx in set(indices):  # Not to use duplicates
            vertex_offset = (idx * stride) + element_offset
            vertex_bytes = buffer_bytes[vertex_offset : vertex_offset + 12]
            
            if len(vertex_bytes) >= 12:
                x, y, z = struct.unpack_from('fff', vertex_bytes, 0)
                vertices[idx] = (x, y, z)

        # 6. Make .obj file
        obj_lines = []
        obj_lines.append(f"# Exported from RenderDoc EID {target_eid} ({buffer_name})")
        
        # Reindex
        idx_mapping = {}
        new_idx = 1
        
        for old_idx in sorted(vertices.keys()):
            x, y, z = vertices[old_idx]
            obj_lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
            idx_mapping[old_idx] = new_idx
            new_idx += 1
            
        # Group indices into threes
        for i in range(0, len(indices), 3):
            if i + 2 < len(indices):

                # Get new vertex index (numbering starts from one)
                v1 = idx_mapping.get(indices[i])
                v2 = idx_mapping.get(indices[i+1])
                v3 = idx_mapping.get(indices[i+2])
                
                if v1 and v2 and v3:
                    obj_lines.append(f"f {v1} {v2} {v3}")

        # 7. Save it to disk
        file_name = f"{clean_buffer_name}.obj"
        full_path = os.path.join(output_dir, file_name)
        
        with open(full_path, "w", encoding="utf-8") as f:
            f.write("\n".join(obj_lines))
            
        print(f"[Success] Exported EID {target_eid} -> {file_name} ({len(vertices)} vertices, {len(indices)//3} triangles)")

    print(f"\nAll the meshes successfully saved to folder: {os.path.abspath(output_dir)}")

# Launch the script
pyrenderdoc.Replay().AsyncInvoke(export_all_indexed_drawcalls_to_obj)