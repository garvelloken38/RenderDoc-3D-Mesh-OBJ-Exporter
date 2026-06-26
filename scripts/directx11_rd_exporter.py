import struct
import os
import renderdoc as rd

# Destination folder
output_dir = r".\exported_meshes"
os.makedirs(output_dir, exist_ok=True)

def export_d3d11_meshes_to_obj(controller):
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
            has_indices = getattr(act, 'numIndices', 0) > 0
            is_draw = act.flags & rd.ActionFlags.Drawcall
            
            if is_draw and has_indices:
                draw_elements_actions.append(act)
                
            if act.children:
                collect_draw_elements(act.children)

    collect_draw_elements(root_actions)
    print(f"\n{len(draw_elements_actions)} indexed actions for export have been found")

    # 3. Iterate over all EID
    for action in draw_elements_actions:
        target_eid = action.eventId
        
        controller.SetFrameEvent(target_eid, True)
        
        d3d11_pipe = controller.GetD3D11PipelineState()
        if d3d11_pipe is None:
            continue
            
        ia = d3d11_pipe.inputAssembly
        
        if not hasattr(ia, 'layouts') or not hasattr(ia, 'vertexBuffers') or not hasattr(ia, 'indexBuffer'):
            continue
        if not ia.layouts or not ia.vertexBuffers:
            continue
        
        attr_index = 0  # POSITION0 by default 

        layout = ia.layouts[attr_index]
        bind_slot = layout.inputSlot        # Get the slot number
        element_offset = layout.byteOffset  
        
        if bind_slot >= len(ia.vertexBuffers):
            continue
        
         # Get the vertex buffer information
        vertex_binding = ia.vertexBuffers[bind_slot]
        vertex_buffer_id = vertex_binding.resourceId        # Unique buffer ID in memory
        stride = vertex_binding.byteStride                  # Vertex size in bytes
        vb_offset = vertex_binding.byteOffset               # Where the model data begins in buffer
        
        if vertex_buffer_id == rd.ResourceId.Null() or stride == 0:
            continue

        # Get the readable file name 
        buffer_name = resource_names.get(vertex_buffer_id, f"buffer_{target_eid}")
        clean_buffer_name = "".join([c if c.isalnum() or c in "@_-" else "_" for c in buffer_name])

        ib_binding = ia.indexBuffer                         # Buffer with indices
        ib_id = ib_binding.resourceId                       # It's id
        
        num_indices = action.numIndices                     # How many indices do the model have
        if ib_id == rd.ResourceId.Null() or num_indices == 0:
            continue
            
        idx_format = getattr(ib_binding, 'byteStride', 2)   # Index size in bytes
        if idx_format == 0:
            idx_format = 2  # Fallback to 2 bytes
            
        ib_offset = action.indexOffset                      # From which byte necessary indices begin
        
        # Get the indices    
        ib_bytes = controller.GetBufferData(ib_id, ib_offset, idx_format * num_indices)
        fmt = f"{num_indices}H" if idx_format == 2 else f"{num_indices}I"

        try:
            indices = list(struct.unpack_from(fmt, ib_bytes, 0))
        except Exception:
            continue

        if not indices:
            continue
        
        max_idx = max(indices)
        buffer_bytes = controller.GetBufferData(vertex_buffer_id, vb_offset, stride * (max_idx + 1))

        vertices = {}
        for idx in set(indices):
            vertex_offset = (idx * stride) + element_offset
            vertex_bytes = buffer_bytes[vertex_offset : vertex_offset + 12]
            
            if len(vertex_bytes) >= 12:
                x, y, z = struct.unpack_from('fff', vertex_bytes, 0)
                vertices[idx] = (x, y, z)

        if not vertices:
            continue

        # 6. Make .obj file
        obj_lines = []
        obj_lines.append(f"# Exported from RenderDoc D3D11 EID {target_eid} ({buffer_name})")
        
        idx_mapping = {}
        new_idx = 1
        
        for old_idx in sorted(vertices.keys()):
            x, y, z = vertices[old_idx]
            obj_lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
            idx_mapping[old_idx] = new_idx
            new_idx += 1
            
        for i in range(0, len(indices), 3):
            if i + 2 < len(indices):
                v1 = idx_mapping.get(indices[i])
                v2 = idx_mapping.get(indices[i+1])
                v3 = idx_mapping.get(indices[i+2])
                if v1 and v2 and v3:
                    obj_lines.append(f"f {v1} {v2} {v3}")

        # 7. Save it to disk
        file_name = f"{clean_buffer_name}.obj"
        full_path = os.path.join(output_dir, file_name)
        
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write("\n".join(obj_lines))
            print(f"[Success] Exported EID {target_eid} -> {file_name} ({len(vertices)} vertices, {len(indices)//3} triangles)")
        except Exception as e:
            print(f"Error writing EID {target_eid}: {e}")

    print(f"\nAll the meshes successfully saved to folder: {os.path.abspath(output_dir)}")

# Launch the script
pyrenderdoc.Replay().AsyncInvoke(export_d3d11_meshes_to_obj)