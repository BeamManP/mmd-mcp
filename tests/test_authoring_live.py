import struct,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from mmd_mcp.pmx_geometry import read_pmx_geometry
from mmd_mcp.pose_authoring import read_profile,compile_pose,SemanticPose
from mmd_mcp import accessory_controls as accessory,authoring_live as live
from mmd_mcp.bone_controls import AxisValues

class GeometryAndLiveTests(unittest.TestCase):
 def pmx(self):
  def text(s):
   b=s.encode('utf-8');return struct.pack('<i',len(b))+b
  header=b'PMX '+struct.pack('<f9B',2.,8,1,0,1,1,1,1,1,1)
  # Empty vertex/index/texture/material sections followed by one fixed-axis bone.
  bone=text('root')+text('root')+struct.pack('<3fbiH',0.,1.,0.,-1,0,0x400)+struct.pack('<6f',0.,1.,0.,1.,0.,0.)
  return header+text('fixture')+text('')+text('')+text('')+bytes(16)+struct.pack('<i',1)+bone
 def test_pmx_bone_section_and_bounds(self):
  data=self.pmx();name,bones=read_pmx_geometry(data)
  self.assertEqual(name,'fixture');self.assertEqual(bones[0]['fixed_axis'],(1.,0.,0.))
  for bad in [data[:10],data[:-1],b'BAD '+data[4:],data[:8]+b'\xff'+data[9:]]:
   with self.assertRaises(ValueError):read_pmx_geometry(bad)
 def test_unprofiled_model_cannot_compile(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'model.pmx';p.write_bytes(self.pmx())
   self.assertIsNone(read_profile(str(p))['semantic_profile'])
   with self.assertRaisesRegex(ValueError,'no calibrated'):
    compile_pose(str(p),SemanticPose())
 def test_preview_refuses_unregistered_evaluation_without_opt_in(self):
  with patch.object(live,'UIReader') as reader:
   for args in [(0,30,1,False),(0,999,1,True),(0,30,0,True),(0,30,True,True)]:
    with self.assertRaises(ValueError):live.preview_motion('C:/fixture-new',*args,1)
   reader.assert_not_called()
 def test_preview_failure_does_not_blindly_restore_frame(self):
  with tempfile.TemporaryDirectory() as folder:
   reader=MagicMock();reader.target.hwnd=1
   with (patch.object(live,'UIReader',return_value=reader),patch.object(live.scene,'context',return_value=('0',1,'m')),
        patch.object(live.scene,'_set_frame') as move,patch.object(live,'capture_png',side_effect=RuntimeError('capture failed')),
        patch.object(live.time,'sleep')):
    with self.assertRaisesRegex(RuntimeError,'frame was not blindly restored'):
     live.preview_motion(str(Path(folder)/'preview'),3,6,3,True,1)
    move.assert_called_once_with(3,1)
 def test_accessory_load_refuses_collapsed_panel_before_native_action(self):
  from mmd_mcp import file_operations as files
  reader=MagicMock();reader.combo.return_value=None
  with (patch.object(files,'file_path',return_value=Path('C:/fixture.x')),
        patch.object(files,'UIReader',return_value=reader),patch.object(files,'context'),
        patch.object(files,'get_ui_state',return_value={}),patch.object(files.win32gui,'PostMessage') as post):
   with self.assertRaisesRegex(ValueError,'Expand the accessory panel'):
    files.load_file('accessory','C:/fixture.x',1)
   post.assert_not_called()
 def test_accessory_values_and_selection_guard_preflight(self):
  for args in [{'scale':0.},{'scale':float('inf')},{'opacity':1.1}]:
   with patch.object(accessory,'UIReader') as reader:
    with self.assertRaises(ValueError):accessory.set_accessory(**args)
    reader.assert_not_called()
  with patch.object(accessory,'UIReader'),patch.object(accessory.scene,'context'),patch.object(accessory,'state',return_value={'selector':{'selected_index':1}}),patch.object(accessory,'_message') as native:
   with self.assertRaisesRegex(ValueError,'Expected accessory'):
    accessory.set_accessory(position=AxisValues(x=3.),expected_index=0,hwnd=1)
   native.assert_not_called()

if __name__=='__main__':unittest.main()
