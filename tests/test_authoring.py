import unittest, math, tempfile, struct
from pathlib import Path
from pydantic import ValidationError
from mmd_mcp.rotation import from_ui, to_ui
from mmd_mcp.motion_document import *

class AuthoringTests(unittest.TestCase):
 def test_rotation_roundtrip_including_gimbal(self):
  for angles in [(10,20,30),(45,30,60),(-65,-120,170),(90,30,50),(-90,30,50),(100,150,20)]:
   q=from_ui(*angles); recovered=from_ui(*to_ui(q))
   self.assertAlmostEqual(abs(sum(a*b for a,b in zip(q,recovered))),1.,places=10)
 def test_measured_mmd_rotation(self):
  # Independently formed standard RH Rz(30) Ry(20) Rx(10).
  q=(.0381345765,.1893078574,.2392983377,.9515485246)
  for actual, expected in zip(to_ui(q),(-1.033,-22.246,-28.029)):
   self.assertAlmostEqual(actual,expected,delta=.002)
 def document(self):
  return MotionDocument(model_name='初音ミク',model_sha256='a'*64,bones=[BoneKey(name='左腕',frame=0)])
 def test_duplicate_keys_and_invalid_curves(self):
  with self.assertRaises(ValidationError):
   MotionDocument(model_name='m',model_sha256='a'*64,bones=[BoneKey(name='a',frame=1)]*2)
  for data in [{'x1':100,'x2':10},{'x1':True},{'y1':128}]:
   with self.assertRaises(ValidationError):Curve(**data)
  with self.assertRaises(ValidationError):BoneKey(name='b',frame=True)
  with self.assertRaises(ValidationError):Vector(x=float('nan'))
 def test_edit_delete_move_and_no_mutation(self):
  doc=self.document(); key=BoneKey(name='左腕',frame=30,interpolation=Interpolation(rotation=Curve(x1=30,y1=0,x2=100,y2=127)))
  edited=edit_document(doc,[KeyEdit(action='delete_bone',name='左腕',frame=0),KeyEdit(action='upsert_bone',name='左腕',frame=30,bone=key)])
  self.assertEqual(doc.bones[0].frame,0);self.assertEqual(edited.bones,[key])
  with self.assertRaises(ValueError):edit_document(doc,[KeyEdit(action='delete_bone',name='左腕',frame=9)])
 def test_export_layout_and_curve(self):
  doc=self.document();doc.bones[0].rotation_degrees=Vector(x=10,y=20,z=30)
  doc.bones[0].interpolation.rotation=Curve(x1=30,y1=0,x2=100,y2=127)
  data=vmd_bytes(doc)
  self.assertEqual(struct.unpack_from('<I',data,50)[0],1)
  self.assertEqual(struct.unpack_from('<4f',data,85),struct.unpack('<4f',struct.pack('<4f',*from_ui(10,20,30))))
  self.assertEqual(data[101+48],30);self.assertEqual(data[101+52],0)
  self.assertEqual(data[101+16],20);self.assertEqual(data[101+20],20)
  self.assertEqual(data[101+56],100);self.assertEqual(data[101+60],127)
  self.assertEqual(len(data),54+111+4+16)
 def test_new_file_only_and_json_roundtrip(self):
  with tempfile.TemporaryDirectory() as folder:
   path=str(Path(folder)/'motion.json');doc=self.document()
   save_document(doc,path);self.assertEqual(read_document(path),doc)
   with self.assertRaises(FileExistsError):save_document(doc,path)
 def test_no_silent_name_truncation(self):
  for name in ['longlonglonglonglong','a\x00b','😀']:
   with self.assertRaises((ValueError,UnicodeError)):
    MotionDocument(model_name='m',model_sha256='a'*64,bones=[BoneKey(name=name,frame=0)])

if __name__=='__main__':unittest.main()
