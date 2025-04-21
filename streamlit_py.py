import streamlit as st
import xml.etree.ElementTree as ET
import os
import zipfile
import tempfile
import uuid
from datetime import datetime
import base64
import io
import re

st.set_page_config(page_title="Rise TinCan to IMSCC Converter", page_icon="📚", layout="wide")

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

# Additional HTML files
st.subheader("Additional HTML Pages")
st.write("Upload any additional HTML files you want to include as wiki content in your IMSCC package.")
additional_html_files = st.file_uploader("Upload HTML files", type=["html"], accept_multiple_files=True)

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

def organize_activities(activities):
    """Organize activities into modules and pages based on sections and blocks"""
    modules = []
    current_module = None
    
    for activity in activities:
        if activity['type'] == 'section':
            # Start a new module
            current_module = {
                'title': activity['name'],
                'id': activity['id'],
                'pages': []
            }
            modules.append(current_module)
        elif activity['type'] == 'block' and current_module is not None:
            # Add block as a page to the current module
            current_module['pages'].append(activity)
    
    return modules

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

def create_safe_filename(title):
    """Create a safe filename from a title"""
    safe_title = re.sub(r'[^\w\s-]', '', title.lower().strip())
    safe_title = re.sub(r'[-\s]+', '-', safe_title)
    return safe_title

def create_html_page(lesson_id, lesson_title, base_url, url_format="blocks"):
    """Create an HTML page with an iframe pointing to the Rise content"""
    
    # Create a unique identifier for the page
    identifier = f"g{uuid.uuid4().hex[:32]}"
    safe_title = create_safe_filename(lesson_title)
    
    html_template = f"""<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
<title>{lesson_title}</title>
<meta name="identifier" content="{identifier}"/>
<meta name="editing_roles" content="teachers"/>
<meta name="workflow_state" content="active"/>
</head>
<body>
<p><iframe style="overflow: hidden; height: 720px; width: 100%;" src="{base_url}/index.html#/{url_format}/{lesson_id}" loading="lazy"></iframe></p>
</body>
</html>"""
    
    return html_template, safe_title, identifier

def extract_wiki_metadata(html_content):
    """Extract metadata from an HTML file"""
    try:
        # Find title
        title_match = re.search(r'<title>(.*?)</title>', html_content)
        title = title_match.group(1) if title_match else "Untitled Page"
        
        # Find identifier
        identifier_match = re.search(r'<meta name="identifier" content="(.*?)"', html_content)
        identifier = identifier_match.group(1) if identifier_match else f"g{uuid.uuid4().hex[:32]}"
        
        # Find workflow state
        workflow_match = re.search(r'<meta name="workflow_state" content="(.*?)"', html_content)
        workflow_state = workflow_match.group(1) if workflow_match else "active"
        
        return {
            'title': title,
            'identifier': identifier,
            'workflow_state': workflow_state
        }
    except Exception as e:
        return {
            'title': "Untitled Page",
            'identifier': f"g{uuid.uuid4().hex[:32]}",
            'workflow_state': "active"
        }

def create_imsmanifest(course_title, modules, additional_pages):
    """Create the imsmanifest.xml file for IMSCC"""
    
    resources_xml = ""
    modules_xml = ""
    
    # Create a unique identifier for the organization
    org_identifier = f"org_{uuid.uuid4().hex[:8]}"
    
    # Create content for each module
    for i, module in enumerate(modules):
        module_id = f"g{uuid.uuid4().hex[:32]}"
        
        # Create module item
        modules_xml += f"""
        <item identifier="{module_id}">
            <title>{module['title']}</title>"""
        
        # Add pages to the module
        for page in module['pages']:
            # Get page metadata
            safe_filename = f"{create_safe_filename(page['name'])}.html"
            page_identifier = f"g{uuid.uuid4().hex[:32]}"
            page['identifier'] = page_identifier  # Store for later use
            
            # Create item entry in the module
            modules_xml += f"""
            <item identifier="g{uuid.uuid4().hex[:32]}" identifierref="{page_identifier}">
                <title>{page['name']}</title>
            </item>"""
            
            # Create resource entry - using the proper format with href at the resource level
            # Updated paths to use wiki_content directly
            resources_xml += f"""
    <resource type="webcontent" identifier="{page_identifier}" href="wiki_content/{safe_filename}">
        <file href="wiki_content/{safe_filename}"/>
    </resource>"""
        
        # Close the module item
        modules_xml += """
        </item>"""
    
    # Add additional HTML pages as resources if any
    for page in additional_pages:
        # Updated paths to use wiki_content directly
        resources_xml += f"""
    <resource type="webcontent" identifier="{page['identifier']}" href="wiki_content/{page['filename']}">
        <file href="wiki_content/{page['filename']}"/>
    </resource>"""
    
    # Create organizations structure with LearningModules
    organizations_xml = f"""
    <organizations>
        <organization identifier="{org_identifier}" structure="rooted-hierarchy">
            <item identifier="LearningModules">
{modules_xml}
            </item>
        </organization>
    </organizations>"""
    
    manifest_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="manifest_{uuid.uuid4().hex[:8]}" 
         xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1" 
         xmlns:lom="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource" 
         xmlns:lomimscc="http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest" 
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
         xsi:schemaLocation="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1 http://www.imsglobal.org/profile/cc/ccv1p1/ccv1p1_imscp_v1p2_v1p0.xsd http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource http://www.imsglobal.org/profile/cc/ccv1p1/LOM/ccv1p1_lomresource_v1p0.xsd http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest http://www.imsglobal.org/profile/cc/ccv1p1/LOM/ccv1p1_lommanifest_v1p0.xsd">
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
  {organizations_xml}
  <resources>
    {resources_xml}
  </resources>
</manifest>
"""
    
    return manifest_xml

def create_module_meta(modules, additional_pages, course_title):
    """Create the module_meta.xml file for Canvas"""
    
    modules_xml = ""
    
    # Create module entries for the Rise content
    for i, module in enumerate(modules):
        module_id = f"m_{uuid.uuid4().hex[:8]}"
        
        items_xml = ""
        for j, page in enumerate(module['pages']):
            item_id = f"i_{uuid.uuid4().hex[:8]}"
            
            # Use the identifier we stored when creating the manifest - this is the key change
            page_identifier = page.get('identifier')
            if not page_identifier:
                # This shouldn't happen if manifest is created first, but just in case
                page_identifier = f"g{uuid.uuid4().hex[:32]}"
            
            # Create item with WikiPage content_type and link_settings_json
            items_xml += f"""
      <item identifier="{item_id}">
        <content_type>WikiPage</content_type>
        <workflow_state>active</workflow_state>
        <title>{page['name']}</title>
        <identifierref>{page_identifier}</identifierref>
        <position>{j+1}</position>
        <new_tab/>
        <indent>0</indent>
        <link_settings_json>null</link_settings_json>
      </item>"""
        
        modules_xml += f"""
  <module identifier="{module_id}">
    <title>{module['title']}</title>
    <workflow_state>active</workflow_state>
    <position>{i+1}</position>
    <items>{items_xml}
    </items>
  </module>"""
    
    # Create "Additional Content" module for the additional HTML pages if they exist
    if additional_pages:
        additional_module_id = f"m_{uuid.uuid4().hex[:8]}"
        
        items_xml = ""
        for j, page in enumerate(additional_pages):
            item_id = f"i_{uuid.uuid4().hex[:8]}"
            
            # Use the existing identifier from the page - this should match what's in the manifest
            page_identifier = page['identifier']
            
            # Create item with WikiPage content_type and link_settings_json
            items_xml += f"""
      <item identifier="{item_id}">
        <content_type>WikiPage</content_type>
        <workflow_state>{page['workflow_state']}</workflow_state>
        <title>{page['title']}</title>
        <identifierref>{page_identifier}</identifierref>
        <position>{j+1}</position>
        <new_tab/>
        <indent>0</indent>
        <link_settings_json>null</link_settings_json>
      </item>"""
        
        # Add additional content module at the end
        modules_xml += f"""
  <module identifier="{additional_module_id}">
    <title>Additional Content</title>
    <workflow_state>active</workflow_state>
    <position>{len(modules)+1}</position>
    <items>{items_xml}
    </items>
  </module>"""
    
    module_meta_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<modules xmlns="http://canvas.instructure.com/xsd/cccv1p0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://canvas.instructure.com/xsd/cccv1p0 https://canvas.instructure.com/xsd/cccv1p0.xsd">{modules_xml}
</modules>
"""
    
    return module_meta_xml

def create_course_settings(course_title, modules, additional_pages):
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
    
    # Create module_meta.xml with the proper module structure
    module_meta_xml = create_module_meta(modules, additional_pages, course_title)
    
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

def process_additional_html(html_files):
    """Process additional HTML files"""
    additional_pages = []
    
    for html_file in html_files:
        try:
            # Read HTML content
            html_content = html_file.read().decode('utf-8')
            
            # Extract metadata
            metadata = extract_wiki_metadata(html_content)
            
            # Add to additional pages
            additional_pages.append({
                'title': metadata['title'],
                'identifier': metadata['identifier'],
                'workflow_state': metadata['workflow_state'],
                'filename': html_file.name,
                'content': html_content
            })
        except Exception as e:
            st.warning(f"Error processing {html_file.name}: {str(e)}")
    
    return additional_pages

def create_imscc_package(activities, course_info, base_url, url_format, additional_html_files):
    """Create an IMSCC package with the extracted activities organized into modules"""
    
    # Organize activities into modules based on sections
    modules = organize_activities(activities)
    
    # Process additional HTML files
    additional_pages = process_additional_html(additional_html_files)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create directory structure - updated to put wiki_content in root
        wiki_dir = os.path.join(temp_dir, "wiki_content")
        course_settings_dir = os.path.join(temp_dir, "course_settings")
        os.makedirs(wiki_dir, exist_ok=True)
        os.makedirs(course_settings_dir, exist_ok=True)
        
        # Create HTML files for each page in each module
        for module in modules:
            for page in module['pages']:
                html_content, safe_title, identifier = create_html_page(page['id'], page['name'], base_url, url_format)
                page_filename = f"{safe_title}.html"
                page['identifier'] = identifier  # Store identifier for use in manifest
                with open(os.path.join(wiki_dir, page_filename), 'w', encoding='utf-8') as f:
                    f.write(html_content)
        
        # Save additional HTML files
        for page in additional_pages:
            with open(os.path.join(wiki_dir, page['filename']), 'w', encoding='utf-8') as f:
                f.write(page['content'])
        
        # Create imsmanifest.xml
        manifest_content = create_imsmanifest(course_info['title'], modules, additional_pages)
        with open(os.path.join(temp_dir, "imsmanifest.xml"), 'w', encoding='utf-8') as f:
            f.write(manifest_content)
        
        # Create course settings files
        course_settings = create_course_settings(course_info['title'], modules, additional_pages)
        for file_path, content in course_settings.items():
            full_path = os.path.join(temp_dir, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
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
        return memory_file, len(modules), len(additional_pages)

if uploaded_file is not None and base_url:
    # Process the uploaded file
    try:
        xml_content = uploaded_file.read().decode('utf-8')
        
        # Extract activities and course info
        activities = extract_activities(xml_content)
        course_info = get_course_info(xml_content)
        
        # Organize into modules
        modules = organize_activities(activities)
        
        # Display extracted information
        st.subheader("Extracted Course Information")
        st.write(f"Title: {course_info['title']}")
        st.write(f"Total modules: {len(modules)}")
        st.write(f"Total Rise activities: {len(activities)}")
        
        if additional_html_files:
            st.write(f"Additional HTML files: {len(additional_html_files)}")
            for html_file in additional_html_files:
                st.write(f"- {html_file.name}")
        
        # Display modules and pages
        st.subheader("Modules and Pages Structure")
        for i, module in enumerate(modules):
            st.write(f"**Module {i+1}: {module['title']}**")
            for page in module['pages']:
                st.write(f"- Page: {page['name']}")
        
        # Create IMSCC package button
        if st.button("Generate IMSCC Package"):
            with st.spinner("Generating IMSCC package..."):
                zipfile_bytes, module_count, additional_count = create_imscc_package(
                    activities, course_info, base_url, url_format, additional_html_files)
                
                # Create download button
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                course_name = re.sub(r'[^\w\s-]', '', course_info['title']).strip().lower()
                course_name = re.sub(r'[-\s]+', '-', course_name)
                filename = f"{course_name}_{timestamp}.imscc"
                
                st.success(f"IMSCC package generated successfully with {module_count} modules and {additional_count} additional pages!")
                
                # Provide download link
                b64 = base64.b64encode(zipfile_bytes.getvalue()).decode()
                href = f'<a href="data:application/zip;base64,{b64}" download="{filename}">Download IMSCC Package</a>'
                st.markdown(href, unsafe_allow_html=True)
    except Exception as e:
        st.error(f"Error processing the file: {str(e)}")
        import traceback
        st.error(traceback.format_exc())
else:
    # Show instructions
    st.info("""
    ## Instructions
    
    1. Upload your Rise TinCan XML file.
    2. Enter the base URL of your Rise content.
    3. Select the appropriate URL format for your Rise content.
    4. (Optional) Upload additional HTML files to include as wiki content.
    5. Click "Generate IMSCC Package" to create an IMSCC package.
    6. Download the IMSCC file and import it into Canvas.
    
    ### Content Organization
    - Activities marked as 'section' will become Canvas modules
    - Activities marked as 'block' will become pages within their respective modules
    - Each new section starts a new standalone module
    - Additional HTML files will be included as wiki content in their own module
    """)
