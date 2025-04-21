import streamlit as st
import xml.etree.ElementTree as ET
import os
import zipfile
import tempfile
import uuid
from datetime import datetime
import base64
import io
import shutil
import re

st.set_page_config(page_title="Rise to IMSCC Converter", page_icon="📚", layout="wide")

st.title("Rise TinCan to IMSCC Converter")
st.write("This app converts a Rise TinCan XML file into an IMSCC package for Canvas.")

# File uploader for tincan.xml
uploaded_file = st.file_uploader("Upload your tincan.xml file", type=["xml"])

# Base URL input
base_url = st.text_input("Enter the base URL for the Rise content (without /index.html):", 
                         placeholder="e.g., https://example.com/rise-content")

# Add URL format options
url_format = st.selectbox(
    "Select the URL format to access Rise content:", 
    options=[
        "blocks", 
        "lessons",
        "sections"
    ],
    index=0,
    help="Choose how to reference specific content in your Rise course."
)

def extract_activities(xml_content):
    """Extract activities marked as blocks and sections from tincan XML"""
    root = ET.fromstring(xml_content)
    
    # Define namespaces
    namespaces = {
        'tincan': 'http://projecttincan.com/tincan.xsd',
        'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
        'xsd': 'http://www.w3.org/2001/XMLSchema'
    }
    
    activities = []
    
    # Find all activities
    for activity in root.findall('.//tincan:activity', namespaces):
        activity_id = activity.get('id')
        activity_type = activity.get('type')
        
        # Get name and check if it's a block or section
        name_elem = activity.find('./tincan:name', namespaces)
        if name_elem is not None:
            name = name_elem.text
            
            # Check if name ends with /blocks or /section
            is_block = name.endswith('/blocks')
            is_section = name.endswith('/section')
            
            if is_block or is_section:
                # Extract the ID part from the full activity ID
                lesson_id = activity_id.split('/')[-1]
                
                # Get description
                description_elem = activity.find('./tincan:description', namespaces)
                description = description_elem.text if description_elem is not None else ""
                
                # Clean up name by removing the /blocks or /section suffix
                clean_name = name.replace('/blocks', '').replace('/section', '')
                
                activities.append({
                    'id': lesson_id,
                    'full_id': activity_id,
                    'name': clean_name,
                    'description': description,
                    'type': 'block' if is_block else 'section'
                })
    
    return activities

def get_course_info(xml_content):
    """Extract course title and description from tincan XML"""
    root = ET.fromstring(xml_content)
    
    namespaces = {
        'tincan': 'http://projecttincan.com/tincan.xsd',
        'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
        'xsd': 'http://www.w3.org/2001/XMLSchema'
    }
    
    # Find the course activity (first activity of type course)
    course_activity = root.find('.//tincan:activity[@type="http://adlnet.gov/expapi/activities/course"]', namespaces)
    
    if course_activity is not None:
        name_elem = course_activity.find('./tincan:name', namespaces)
        desc_elem = course_activity.find('./tincan:description', namespaces)
        
        course_title = name_elem.text if name_elem is not None else "Untitled Course"
        course_description = desc_elem.text if desc_elem is not None else ""
        
        return {
            'title': course_title,
            'description': course_description
        }
    
    return {'title': "Untitled Course", 'description': ""}

def create_html_page(lesson_id, lesson_title, lesson_description, base_url, url_format="blocks"):
    """Create an HTML page with an iframe pointing to the Rise content"""
    
    # Sanitize the title for use in filenames and IDs
    safe_title = re.sub(r'[^\w\s-]', '', lesson_title).strip().lower()
    safe_title = re.sub(r'[-\s]+', '-', safe_title)
    
    html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{lesson_title}</title>
    <style>
        body, html {{
            margin: 0;
            padding: 0;
            height: 100%;
            overflow: hidden;
        }}
        .container {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
        }}
        iframe {{
            width: 100%;
            height: 100%;
            border: none;
        }}
    </style>
</head>
<body>
    <div class="container">
        <iframe src="{base_url}/index.html#/{url_format}/{lesson_id}" allowfullscreen></iframe>
    </div>
</body>
</html>
"""
    
    return html_template

def create_imsmanifest(course_title, activities):
    """Create the imsmanifest.xml file for IMSCC"""
    
    resources_xml = ""
    organizations_xml = ""
    
    # Create a unique identifier for the organization
    org_identifier = f"org_{uuid.uuid4().hex[:8]}"
    
    # Create resource entries for each activity
    for i, activity in enumerate(activities):
        # Sanitize the title for use in filenames and IDs
        safe_title = re.sub(r'[^\w\s-]', '', activity['name']).strip().lower()
        safe_title = re.sub(r'[-\s]+', '-', safe_title)
        
        # Create resource entry
        resources_xml += f"""
        <resource identifier="resource_{i+1}" type="webcontent">
            <file href="wiki_content/{safe_title}.html"/>
        </resource>"""
        
        # Create organization item entry
        organizations_xml += f"""
            <item identifier="item_{i+1}" identifierref="resource_{i+1}">
                <title>{activity['name']}</title>
            </item>"""
    
    manifest_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="manifest_{uuid.uuid4().hex[:8]}" 
         xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1" 
         xmlns:lom="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource" 
         xmlns:lomimscc="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest" 
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
         xsi:schemaLocation="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1 http://www.imsglobal.org/xsd/imscp_v1p1.xsd http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource http://www.imsglobal.org/profile/cc/ccv1p1/LOM/ccv1p1_lomresource_v1p0.xsd http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest http://www.imsglobal.org/profile/cc/ccv1p1/LOM/ccv1p1_lommanifest_v1p0.xsd">
  <metadata>
    <schema>IMS Common Cartridge</schema>
    <schemaversion>1.1.0</schemaversion>
    <lomimscc:lom>
      <lomimscc:general>
        <lomimscc:title>
          <lomimscc:string>{course_title}</lomimscc:string>
        </lomimscc:title>
      </lomimscc:general>
    </lomimscc:lom>
  </metadata>
  
  <organizations>
    <organization identifier="{org_identifier}" structure="rooted-hierarchy">
      <item identifier="root_item">
        <title>{course_title}</title>
        {organizations_xml}
      </item>
    </organization>
  </organizations>
  
  <resources>
    {resources_xml}
  </resources>
</manifest>
"""
    
    return manifest_xml

def create_course_settings(course_title):
    """Create necessary course settings files for IMSCC"""
    
    # Create course_settings/canvas_export.txt
    canvas_export = "1"
    
    # Create course_settings/course_settings.xml
    course_settings_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<course identifier="{uuid.uuid4().hex}" xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">
  <title>{course_title}</title>
  <course_code></course_code>
  <locale>en</locale>
  <settings>
    <setting name="hide_final_grades">false</setting>
    <setting name="allow_student_discussion_topics">true</setting>
    <setting name="allow_student_discussion_editing">true</setting>
    <setting name="allow_student_forum_attachments">false</setting>
    <setting name="allow_student_organized_groups">false</setting>
    <setting name="show_all_discussion_entries">false</setting>
    <setting name="is_public">false</setting>
    <setting name="open_enrollment">false</setting>
    <setting name="allow_wiki_comments">false</setting>
    <setting name="self_enrollment">false</setting>
    <setting name="allow_student_assignment_edits">false</setting>
    <setting name="allow_student_discussion_reporting">true</setting>
    <setting name="restrict_student_past_view">false</setting>
    <setting name="restrict_student_future_view">false</setting>
    <setting name="grading_standard_enabled">false</setting>
  </settings>
  <date_format>iso8601</date_format>
</course>
"""
    
    # Create course_settings/module_meta.xml
    module_meta_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<modules xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">
  <module identifier="{uuid.uuid4().hex}">
    <title>{course_title} Content</title>
    <workflow_state>active</workflow_state>
    <position>1</position>
    <items></items>
  </module>
</modules>
"""
    
    # Create other necessary empty files
    other_files = {
        "course_settings/assignment_groups.xml": """<?xml version="1.0" encoding="UTF-8"?>
<assignmentGroups xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">
</assignmentGroups>
""",
        "course_settings/files_meta.xml": """<?xml version="1.0" encoding="UTF-8"?>
<files xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">
</files>
""",
        "course_settings/media_tracks.xml": """<?xml version="1.0" encoding="UTF-8"?>
<media_tracks xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">
</media_tracks>
""",
        "course_settings/context.xml": """<?xml version="1.0" encoding="UTF-8"?>
<course_components xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">
  <resource content_type="associated_content" identifierref="" intendeduse="syllabus" type="syllabus">
  </resource>
</course_components>
"""
    }
    
    return {
        "course_settings/canvas_export.txt": canvas_export,
        "course_settings/course_settings.xml": course_settings_xml,
        "course_settings/module_meta.xml": module_meta_xml,
        **other_files
    }

def create_imscc_package(activities, course_info, base_url, url_format):
    """Create an IMSCC package with the extracted activities"""
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create directory structure
        wiki_dir = os.path.join(temp_dir, "wiki_content")
        course_settings_dir = os.path.join(temp_dir, "course_settings")
        os.makedirs(wiki_dir, exist_ok=True)
        os.makedirs(course_settings_dir, exist_ok=True)
        
        # Create HTML files for each activity
        for activity in activities:
            # Sanitize the title for use in filenames
            safe_title = re.sub(r'[^\w\s-]', '', activity['name']).strip().lower()
            safe_title = re.sub(r'[-\s]+', '-', safe_title)
            
            html_content = create_html_page(activity['id'], activity['name'], activity['description'], base_url, url_format)
            with open(os.path.join(wiki_dir, f"{safe_title}.html"), 'w', encoding='utf-8') as f:
                f.write(html_content)
        
        # Create imsmanifest.xml
        manifest_content = create_imsmanifest(course_info['title'], activities)
        with open(os.path.join(temp_dir, "imsmanifest.xml"), 'w', encoding='utf-8') as f:
            f.write(manifest_content)
        
        # Create course settings files
        course_settings = create_course_settings(course_info['title'])
        for file_path, content in course_settings.items():
            full_path = os.path.join(temp_dir, file_path)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
        
        # Create a ZIP file with .imscc extension
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zf.write(file_path, arcname)
        
        memory_file.seek(0)
        return memory_file

if uploaded_file is not None and base_url:
    # Process the uploaded file
    try:
        xml_content = uploaded_file.read().decode('utf-8')
        
        # Extract activities and course info
        activities = extract_activities(xml_content)
        course_info = get_course_info(xml_content)
        
        # Display extracted information
        st.subheader("Extracted Course Information")
        st.write(f"Title: {course_info['title']}")
        st.write(f"Total activities: {len(activities)}")
        
        # Create dataframe for displaying activities
        import pandas as pd
        activities_df = pd.DataFrame(activities)
        activities_df = activities_df.rename(columns={
            'id': 'ID', 
            'name': 'Name', 
            'type': 'Type'
        })
        
        st.subheader("Activities to be Included")
        st.dataframe(activities_df[['ID', 'Name', 'Type']])
        
        # Create IMSCC package button
        if st.button("Generate IMSCC Package"):
            with st.spinner("Generating IMSCC package..."):
                zipfile_bytes = create_imscc_package(activities, course_info, base_url, url_format)
                
                # Create download button
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                filename = f"rise_content_{timestamp}.imscc"
                
                st.success("IMSCC package generated successfully!")
                
                # Provide download link
                b64 = base64.b64encode(zipfile_bytes.getvalue()).decode()
                href = f'<a href="data:application/zip;base64,{b64}" download="{filename}">Download IMSCC Package</a>'
                st.markdown(href, unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Error processing the file: {str(e)}")
else:
    # Show instructions
    st.info("""
    ## Instructions
    
    1. Upload your Rise TinCan XML file.
    2. Enter the base URL of your Rise content.
    3. Select the appropriate URL format for your Rise content.
    4. Click "Generate IMSCC Package" to create an IMSCC package.
    5. Download the IMSCC file and import it into Canvas.
    """)
