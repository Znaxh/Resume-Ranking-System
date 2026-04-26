from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import io
import csv
from datetime import datetime, timezone
import traceback
import json
import numpy as np
import joblib

import app_config
from prompts import VERSION as PROMPT_VERSION
from config.settings import config_dict
from core.algorithm_manager import AlgorithmManager
from utils.file_processor import FileProcessor
from utils.validators import RequestValidator
from api.error_handlers import register_error_handlers
from api.middleware import setup_middleware
from api.routes import get_routes_blueprint
from core.observability import (
    init_observability,
    get_logger,
    resume_ranking_requests_total,
    resume_ranking_latency_seconds,
    resume_ranking_score_distribution,
)
from core.jd_expander import expand_jd, jd_expansion_to_context_block
from core.explainer import explain_match
from core.fairness_monitor import analyze_batch_fairness

log = get_logger(__name__)

# JSON serialization helper function
def convert_to_json_serializable(obj):
    """Convert numpy/torch types to JSON serializable types"""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    elif isinstance(obj, (np.floating, float)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_to_json_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_to_json_serializable(item) for item in obj]
    elif hasattr(obj, 'item'):  # For single-element numpy arrays
        return obj.item()
    else:
        return obj

def create_app(config_name='default'):
    """Application factory"""
    app = Flask(__name__)
    
    # Load configuration
    config = config_dict[config_name]
    app.config.from_object(config)

    init_observability(app)

    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per day", "60 per hour"],
        storage_uri="memory://",
    )
    
    # Enable CORS
    CORS(app, origins=['http://localhost:3000', 'http://localhost:3001'])
    
    # Setup middleware
    setup_middleware(app)
    
    # Register error handlers
    register_error_handlers(app)

    app.register_blueprint(get_routes_blueprint(app), url_prefix="/v2/api")

    @app.after_request
    def _mark_api_version(response):
        if request.path.startswith("/v2/api"):
            response.headers["X-API-Version"] = "v2"
        else:
            response.headers["X-API-Version"] = "legacy"
        return response
    
    # Initialize components
    algorithm_manager = AlgorithmManager(app.config)
    file_processor = FileProcessor(app.config)
    validator = RequestValidator(app.config)
    
    # Create upload directory
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # ===== EXISTING ENDPOINTS =====
    
    @app.route('/api/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'algorithms': algorithm_manager.get_algorithm_status(),
            'version': '1.0.0'
        })
    
    @app.route('/api/algorithms', methods=['GET'])
    def get_algorithms():
        """Get available algorithms"""
        return jsonify(algorithm_manager.get_algorithm_status())
    
    @app.route('/api/positions', methods=['GET'])
    def get_positions():
        """Get available job positions"""
        positions = [
            {'value': 'sde', 'label': 'Software Development Engineer', 'icon': '💻'},
            {'value': 'swe', 'label': 'Software Engineer', 'icon': '⚙️'},
            {'value': 'ml_engineer', 'label': 'ML Engineer', 'icon': '🤖'},
            {'value': 'data_scientist', 'label': 'Data Scientist', 'icon': '📊'},
            {'value': 'devops', 'label': 'DevOps Engineer', 'icon': '🔧'},
            {'value': 'frontend', 'label': 'Frontend Developer', 'icon': '🎨'},
            {'value': 'backend', 'label': 'Backend Developer', 'icon': '🗄️'},
            {'value': 'fullstack', 'label': 'Full Stack Developer', 'icon': '🚀'},
            {'value': 'product_manager', 'label': 'Product Manager', 'icon': '📱'},
            {'value': 'designer', 'label': 'UI/UX Designer', 'icon': '🎭'},
            {'value': 'qa_engineer', 'label': 'QA Engineer', 'icon': '🔍'},
            {'value': 'security_engineer', 'label': 'Security Engineer', 'icon': '🛡️'},
            {'value': 'general', 'label': 'General', 'icon': '📋'}
        ]
        return jsonify(positions)

    @app.route('/api/processing-status/<job_id>', methods=['GET'])
    def processing_status_unavailable(job_id):
        """Reserved for async jobs; ranking is synchronous today."""
        return jsonify({
            'error': (
                'Background job processing is not implemented; '
                'POST /api/process-resumes completes in the same HTTP request.'
            ),
            'job_id': job_id,
        }), 501

    @app.route('/api/cancel-processing/<job_id>', methods=['POST'])
    def cancel_processing_unavailable(job_id):
        """Reserved for async jobs; nothing to cancel for synchronous ranking."""
        return jsonify({
            'error': 'There are no background jobs to cancel; processing is synchronous.',
            'job_id': job_id,
        }), 501
    
    @app.route('/api/export-results', methods=['POST'])
    def export_results():
        """Export ranking results as CSV (matches frontend lib/api.js exportResults)."""
        try:
            body = request.get_json(silent=True) or {}
            fmt = (body.get('format') or 'csv').lower().strip()
            if fmt != 'csv':
                return jsonify({'error': 'Only format=csv is supported currently'}), 400

            payload = body.get('results')
            if payload is None:
                return jsonify({'error': 'Missing results in request body'}), 400
            if isinstance(payload, dict):
                rows = payload.get('results') or []
            elif isinstance(payload, list):
                rows = payload
            else:
                return jsonify({'error': 'results must be an object or list'}), 400

            if not rows:
                return jsonify({'error': 'No result rows to export'}), 400

            algorithms = set()
            for row in rows:
                scores = row.get('scores') or {}
                if isinstance(scores, dict):
                    algorithms.update(scores.keys())
            algorithms = sorted(algorithms)

            buffer = io.StringIO()
            header = ['rank', 'filename', 'final_score', 'weighted_score', 'confidence', 'explanation']
            header += [f'score_{a}' for a in algorithms]
            header.append('skills_sample')
            writer = csv.writer(buffer)
            writer.writerow(header)

            for row in rows:
                scores = row.get('scores') or {}
                skills = row.get('extracted_skills') or []
                skills_preview = '; '.join(skills[:15]) if skills else ''
                out = [
                    row.get('rank', ''),
                    row.get('filename', ''),
                    row.get('final_score', ''),
                    row.get('weighted_score', ''),
                    row.get('confidence', ''),
                    (row.get('explanation') or '').replace('\n', ' ')[:500],
                ]
                out += [scores.get(a, '') for a in algorithms]
                out.append(skills_preview)
                writer.writerow(out)

            csv_bytes = buffer.getvalue().encode('utf-8')
            filename = f'resume_ranking_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.csv'
            return Response(
                csv_bytes,
                mimetype='text/csv; charset=utf-8',
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Cache-Control': 'no-store',
                },
            )
        except Exception as e:
            log.error(f"Export error: {e}")
            return jsonify({'error': 'Export failed. Please try again.'}), 500

    @app.route('/api/supported-formats', methods=['GET'])
    def get_supported_formats():
        """Get supported file formats"""
        return jsonify({
            'formats': ['.pdf', '.docx', '.doc', '.txt'],
            'max_file_size': app_config.MAX_FILE_SIZE_MB * 1024 * 1024,
            'max_files': app.config['MAX_FILES_PER_REQUEST'],
            'supported_mime_types': [
                'application/pdf',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/msword'
            ]
        })
    
    @app.route('/api/validate-files', methods=['POST'])
    def validate_files():
        """Validate uploaded files without processing"""
        try:
            files = request.files.getlist('files')
            
            if not files:
                return jsonify({'error': 'No files provided'}), 400
            
            validation_results = []
            for i, file in enumerate(files):
                result = file_processor.validate_file(file)
                result['index'] = i
                validation_results.append(result)
            
            return jsonify({
                'results': validation_results,
                'total_files': len(files),
                'valid_files': sum(1 for r in validation_results if r['valid'])
            })
            
        except Exception as e:
            log.error(f"File validation error: {e}")
            return jsonify({'error': 'File validation failed'}), 500
    
    def _explainer_skill_hints(combined_result: dict, resume_text: str, jd: str):
        tops = []
        ner = combined_result.get("algorithm_scores", {}).get("ner", {})
        details = ner.get("details", {}) or {}
        extracted = details.get("extracted_skills", {}) or {}
        for _cat, items in extracted.items():
            for item in items:
                if isinstance(item, dict) and "skill" in item:
                    tops.append(str(item["skill"]))
                elif isinstance(item, str):
                    tops.append(item)
        tops = list(dict.fromkeys(tops))[:20]
        cos = combined_result.get("algorithm_scores", {}).get("cosine", {})
        for term in (cos.get("details", {}) or {}).get("top_matching_terms", [])[:15]:
            if isinstance(term, str):
                tops.append(term)
            elif isinstance(term, dict) and "term" in term:
                tops.append(str(term["term"]))
        tops = list(dict.fromkeys(tops))[:15]
        resume_lower = (resume_text or "").lower()
        missing = []
        for word in (jd or "").lower().replace(",", " ").split():
            w = "".join(c for c in word if c.isalnum())
            if len(w) > 4 and w not in resume_lower:
                missing.append(w)
        missing = list(dict.fromkeys(missing))[:15]
        return tops, missing

    @limiter.limit("30 per minute")
    @app.route('/api/process-resumes', methods=['POST'])
    @app.route('/api/rank', methods=['POST'])
    def process_resumes():
        """Main endpoint for processing resumes"""
        start_time = datetime.now(timezone.utc)
        
        try:
            # Validate request
            validation_result = validator.validate_process_request(request)
            if not validation_result['valid']:
                return jsonify({'error': validation_result['error']}), 400
            
            # Extract request data
            files = request.files.getlist('resumes')
            job_description = request.form.get('jobDescription', '').strip()
            original_jd = job_description
            jd_expansion_used = False
            expanded = expand_jd(job_description) if app_config.USE_LLM_JD_EXPANSION else None
            if expanded:
                job_description = (
                    original_jd
                    + "\n\n[Structured JD expansion]\n"
                    + jd_expansion_to_context_block(expanded)
                )
                jd_expansion_used = True
            position = request.form.get('position', 'general')
            methods = request.form.getlist('methods')
            
            # Check if user wants to use academic ML models
            use_academic_models = request.form.get('useAcademicModels', 'false').lower() == 'true'
            
            # Parse options
            options_str = request.form.get('options', '{}')
            try:
                options = json.loads(options_str)
            except json.JSONDecodeError:
                options = {}
            
            # Parse metadata
            metadata_str = request.form.get('metadata', '{}')
            try:
                metadata = json.loads(metadata_str)
            except json.JSONDecodeError:
                metadata = {}
            
            log.info("processing_request", files=len(files), algorithms=len(methods))
            
            # Process files
            processed_files = file_processor.process_files(files)
            
            # Filter successful extractions
            successful_files = [f for f in processed_files if f['success']]
            failed_files = [f for f in processed_files if not f['success']]
            
            if not successful_files:
                return jsonify({
                    'error': 'No files could be processed successfully',
                    'failed_files': failed_files
                }), 400
            
            # Extract resume texts
            resume_texts = [f['text'] for f in successful_files]
            
            # Process with algorithms (enhanced with academic models)
            if use_academic_models:
                algorithm_results = _process_with_academic_models(
                    resume_texts, job_description, methods, position
                )
            else:
                algorithm_results = algorithm_manager.process_resumes_parallel(
                    resume_texts, job_description, methods, position
                )
            
            # Calculate processing time
            end_time = datetime.now(timezone.utc)
            processing_time = (end_time - start_time).total_seconds()
            
            # Prepare response with JSON serialization
            response = {
                'success': True,
                'timestamp': end_time.isoformat(),
                'processing_time_seconds': float(processing_time),
                'academic_models_used': use_academic_models,
                'jd_expansion_used': jd_expansion_used,
                'prompt_version': PROMPT_VERSION,
                'fairness_warning': None,
                'score_variance': None,
                'score_std_dev': None,
                'summary': {
                    'total_resumes_uploaded': len(files),
                    'successfully_processed': len(successful_files),
                    'failed_to_process': len(failed_files),
                    'algorithms_used': methods,
                    'job_position': position,
                    'processing_options': options
                },
                'results': [],
                'failed_files': failed_files,
                'algorithm_performance': convert_to_json_serializable(algorithm_results.get('algorithm_performance', {})),
                'metadata': {
                    **metadata,
                    'processing_completed_at': end_time.isoformat(),
                    'server_version': '1.0.0',
                    'academic_mode': use_academic_models
                }
            }
            
            # Format results for frontend
            for i, combined_result in enumerate(algorithm_results['combined_results']):
                original_file_info = successful_files[combined_result['resume_index']]
                
                top_sk, miss_sk = _explainer_skill_hints(
                    combined_result,
                    original_file_info['text'],
                    original_jd,
                )
                explanation = explain_match(
                    original_file_info['text'],
                    original_jd,
                    float(combined_result['combined_score']) * 100.0,
                    top_sk,
                    miss_sk,
                    combined_result,
                    position,
                )
                
                # Extract skills if NER was used
                extracted_skills = []
                if 'ner' in combined_result['algorithm_scores']:
                    ner_details = combined_result['algorithm_scores']['ner'].get('details', {})
                    extracted_skills = _extract_skills_list(ner_details.get('extracted_skills', {}))
                
                result_entry = {
                    'filename': original_file_info['filename'],
                    'rank': int(combined_result['rank']),
                    'final_score': float(combined_result['combined_score']),
                    'weighted_score': float(combined_result['weighted_score']),
                    'scores': {alg: float(data['score']) for alg, data in combined_result['algorithm_scores'].items()},
                    'explanation': explanation,
                    'extracted_skills': extracted_skills[:20],
                    'file_info': {
                        'size': int(original_file_info['size']),
                        'word_count': int(original_file_info['word_count']),
                        'char_count': int(original_file_info['char_count'])
                    },
                    'algorithm_details': convert_to_json_serializable(combined_result['algorithm_scores']),
                    'errors': combined_result.get('errors', [])
                }
                
                response['results'].append(result_entry)
            
            # Sort results by rank
            response['results'].sort(key=lambda x: x['rank'])

            fairness = analyze_batch_fairness(
                original_jd,
                [float(r['final_score']) for r in response['results']],
            )
            response['fairness_warning'] = fairness['fairness_warning']
            response['score_variance'] = fairness['score_variance']
            response['score_std_dev'] = fairness['score_std_dev']

            try:
                resume_ranking_latency_seconds.labels(algorithm="ensemble").observe(
                    float(processing_time)
                )
                resume_ranking_requests_total.labels(algorithm="ensemble", status="success").inc()
                for row in response['results']:
                    resume_ranking_score_distribution.observe(float(row['final_score']))
            except Exception:
                pass
            
            log.info(
                "processing_complete",
                resumes=len(successful_files),
                seconds=round(processing_time, 3),
            )
            
            # Final conversion to ensure everything is JSON serializable
            response = convert_to_json_serializable(response)
            
            return jsonify(response)
            
        except Exception as e:
            error_msg = str(e)
            log.error("processing_error", error=error_msg)
            log.error("processing_trace", trace=traceback.format_exc())
            try:
                resume_ranking_requests_total.labels(algorithm="ensemble", status="error").inc()
            except Exception:
                pass
            
            return jsonify({
                'success': False,
                'error': 'An internal error occurred while processing your request.',
                'error_id': f"err_{int(datetime.now(timezone.utc).timestamp())}",
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 500
    
    # ===== NEW ACADEMIC ML ENDPOINTS =====
    
    @app.route('/api/academic/setup-folders', methods=['POST'])
    def setup_academic_folders():
        """Setup academic folder structure for ML training"""
        try:
            from data.dataset_manager import DatasetManager
            dataset_manager = DatasetManager()
            
            return jsonify({
                'success': True,
                'message': 'Academic folder structure created successfully!',
                'folder_structure': {
                    'training_resumes': {
                        'excellent': ['fullstack', 'backend', 'frontend', 'data_scientist', 'devops'],
                        'good': ['fullstack', 'backend', 'frontend', 'data_scientist', 'devops'],
                        'fair': ['fullstack', 'backend', 'frontend', 'data_scientist', 'devops'], 
                        'poor': ['fullstack', 'backend', 'frontend', 'data_scientist', 'devops']
                    },
                    'job_descriptions': ['fullstack_jobs', 'backend_jobs', 'frontend_jobs'],
                    'models': ['trained_models', 'feature_extractors', 'scalers', 'evaluation_results']
                },
                'instructions': {
                    'step_1': 'Add resume files (.txt, .pdf, .docx) to appropriate quality/position folders',
                    'step_2': 'Add job description files to job_descriptions folders',
                    'step_3': 'Use /api/academic/train-models to train ML algorithms',
                    'step_4': 'Use /api/academic/evaluate-models for academic evaluation',
                    'step_5': 'Use useAcademicModels=true in /api/process-resumes for predictions'
                },
                'sample_files_created': True,
                'next_step': 'Add your own resume files to the folders and train models'
            })
            
        except Exception as e:
            log.error(f"Academic folder setup error: {e}")
            return jsonify({'error': 'Failed to set up academic folders.'}), 500
    
    @app.route('/api/academic/dataset-stats', methods=['GET'])
    def get_dataset_stats():
        """Get comprehensive dataset statistics"""
        try:
            from data.dataset_manager import DatasetManager
            dataset_manager = DatasetManager()
            stats = dataset_manager.get_dataset_statistics()
            
            return jsonify({
                'success': True,
                'statistics': stats,
                'academic_insights': {
                    'data_quality_assessment': 'Good' if stats.get('data_quality_score', 0) > 0.7 else 'Needs Improvement',
                    'ready_for_training': stats.get('data_quality_score', 0) > 0.5,
                    'minimum_samples_met': stats.get('dataset_overview', {}).get('total_samples', 0) >= 10,
                    'recommended_improvements': [
                        'Add more samples to underrepresented categories',
                        'Balance quality distribution across positions',
                        'Ensure minimum 20 samples per position/quality combination'
                    ] if stats.get('data_quality_score', 0) < 0.8 else ['Dataset is well-balanced for academic research']
                }
            })
            
        except Exception as e:
            log.error(f"Dataset stats error: {e}")
            return jsonify({'error': 'Failed to retrieve dataset statistics.', 'message': 'Setup academic folders first using /api/academic/setup-folders'}), 500
    
    @app.route('/api/academic/train-models', methods=['POST'])
    def train_academic_models():
        """Train ML models using folder-based dataset"""
        try:
            from data.dataset_manager import DatasetManager
            from sklearn.model_selection import train_test_split
            from sklearn.ensemble import RandomForestRegressor
            from sklearn.neural_network import MLPRegressor
            from sklearn.svm import SVR
            from sklearn.metrics import r2_score, mean_absolute_error
            import joblib
            
            position = request.form.get('position', 'fullstack')
            algorithms = request.form.getlist('algorithms') or ['random_forest', 'neural_network']
            
            dataset_manager = DatasetManager()
            
            # Load and prepare dataset
            log.info(f"Loading academic dataset for position: {position}")
            df, target_scores = dataset_manager.load_training_dataset(position)
            
            if len(df) < 10:
                return jsonify({
                    'error': 'Insufficient training data',
                    'message': f'Only {len(df)} samples found. Minimum 10 required.',
                    'suggestion': 'Add more resume files to the data/training_resumes folders',
                    'current_data': df.groupby(['quality_category', 'position']).size().to_dict() if len(df) > 0 else {}
                }), 400
            
            # Extract features using academic approach
            log.info("Extracting comprehensive feature set...")
            features = dataset_manager.extract_features(df, fit_transform=True)
            
            # Split data for academic validation
            X_train, X_test, y_train, y_test = train_test_split(
                features, target_scores, test_size=0.2, random_state=42,
                stratify=df['quality_label'] if len(df) > 5 else None
            )
            
            # Train selected algorithms
            training_results = {}
            models_dir = os.path.join('data', 'models', 'trained_models')
            os.makedirs(models_dir, exist_ok=True)
            
            for algorithm_name in algorithms:
                try:
                    log.info(f"Training {algorithm_name} with academic dataset...")
                    
                    if algorithm_name == 'random_forest':
                        model = RandomForestRegressor(n_estimators=100, random_state=42, max_depth=10)
                        model.fit(X_train, y_train)
                        y_pred = model.predict(X_test)
                        
                    elif algorithm_name == 'neural_network':
                        model = MLPRegressor(
                            hidden_layer_sizes=(100, 50), 
                            max_iter=500, 
                            random_state=42,
                            early_stopping=True,
                            validation_fraction=0.1
                        )
                        model.fit(X_train, y_train)
                        y_pred = model.predict(X_test)
                        
                    elif algorithm_name == 'svm':
                        model = SVR(kernel='rbf', C=1.0, gamma='scale')
                        model.fit(X_train, y_train)
                        y_pred = model.predict(X_test)
                    elif algorithm_name == 'xgboost':
                        from xgboost import XGBRegressor
                        model = XGBRegressor(
                            n_estimators=100, max_depth=6,
                            learning_rate=0.1, random_state=42
                        )
                        model.fit(X_train, y_train)
                        y_pred = model.predict(X_test)
                    else:
                        continue
                    
                    # Calculate metrics
                    r2 = r2_score(y_test, y_pred)
                    mae = mean_absolute_error(y_test, y_pred)
                    
                    training_results[algorithm_name] = {
                        'r2_score': float(r2),
                        'mean_absolute_error': float(mae),
                        'train_samples': len(X_train),
                        'test_samples': len(X_test),
                        'model_type': type(model).__name__,
                        'training_completed': datetime.now().isoformat()
                    }
                    
                    # Save trained model
                    model_path = os.path.join(models_dir, f'{algorithm_name}_{position}_academic.joblib')
                    joblib.dump(model, model_path)
                    
                    log.info(f"Successfully trained {algorithm_name}: R²={r2:.3f}, MAE={mae:.3f}")
                    
                except Exception as e:
                    log.error(f"Error training {algorithm_name}: {e}")
                    training_results[algorithm_name] = {'error': f'Training failed for {algorithm_name}'}
            
            return jsonify({
                'success': True,
                'training_completed': datetime.now().isoformat(),
                'position': position,
                'dataset_info': {
                    'total_samples': len(df),
                    'training_samples': len(X_train),
                    'test_samples': len(X_test),
                    'feature_count': features.shape[1],
                    'quality_distribution': df['quality_category'].value_counts().to_dict(),
                    'position_distribution': df['position'].value_counts().to_dict()
                },
                'training_results': training_results,
                'models_saved': [alg for alg, result in training_results.items() if 'error' not in result],
                'next_steps': [
                    'Models are now ready for use',
                    'Use useAcademicModels=true in /api/process-resumes',
                    'Use /api/academic/evaluate-models for detailed evaluation'
                ]
            })
            
        except Exception as e:
            log.error(f"Academic training error: {e}")
            return jsonify({'error': 'Model training failed. Check server logs for details.'}), 500
    
    @app.route('/api/academic/evaluate-models', methods=['POST'])
    def evaluate_academic_models():
        """Evaluate trained academic models"""
        try:
            from data.dataset_manager import DatasetManager
            from evaluation.accuracy_evaluator import AccuracyEvaluator
            
            position = request.form.get('position', 'fullstack')
            algorithms = request.form.getlist('algorithms') or ['random_forest', 'neural_network']
            
            dataset_manager = DatasetManager()
            evaluator = AccuracyEvaluator()
            
            # Load test dataset
            df, target_scores = dataset_manager.load_training_dataset(position)
            features = dataset_manager.extract_features(df, fit_transform=False)
            
            evaluation_results = []
            
            for algorithm_name in algorithms:
                try:
                    # Load trained model
                    model_path = os.path.join('data', 'models', 'trained_models', f'{algorithm_name}_{position}_academic.joblib')
                    if not os.path.exists(model_path):
                        continue
                    
                    model = joblib.load(model_path)
                    
                    # Get predictions
                    predictions = model.predict(features)
                    
                    # Evaluate
                    result = evaluator.evaluate_algorithm_predictions(
                        algorithm_name, target_scores, predictions, df
                    )
                    evaluation_results.append(result)
                    
                except Exception as e:
                    log.error(f"Error evaluating {algorithm_name}: {e}")
                    continue
            
            # Generate comparison
            if len(evaluation_results) > 1:
                comparison = evaluator.compare_algorithms(evaluation_results)
            else:
                comparison = None
            
            return jsonify({
                'success': True,
                'evaluation_completed': datetime.now().isoformat(),
                'evaluation_results': convert_to_json_serializable(evaluation_results),
                'comparison': convert_to_json_serializable(comparison) if comparison else None,
                'academic_summary': {
                    'best_algorithm': (
                        comparison['rankings']['top_performer'][0]
                        if comparison
                        and comparison.get('rankings', {}).get('top_performer')
                        else 'N/A'
                    ),
                    'evaluation_metrics_used': ['R²', 'MAE', 'Spearman Correlation', 'Classification Accuracy'],
                    'recommendation': 'Use the top-performing algorithm for production deployment'
                }
            })
            
        except Exception as e:
            log.error(f"Model evaluation error: {e}")
            return jsonify({'error': 'Model evaluation failed. Check server logs for details.'}), 500
    
    # ===== HELPER FUNCTIONS =====
    
    def _process_with_academic_models(resume_texts: list, job_description: str, methods: list, position: str):
        """Process resumes using trained academic ML models"""
        try:
            from data.dataset_manager import DatasetManager
            import pandas as pd
            
            dataset_manager = DatasetManager()
            models_dir = os.path.join('data', 'models', 'trained_models')
            
            # Prepare data for prediction
            prediction_data = []
            for resume_text in resume_texts:
                prediction_data.append({
                    'resume_text': resume_text,
                    'job_description': job_description,
                    'position': position,
                    'quality_category': 'unknown',  # Will be predicted
                    'quality_label': 0,
                    'filename': f'prediction_{len(prediction_data)}'
                })
            
            df = pd.DataFrame(prediction_data)
            features = dataset_manager.extract_features(df, fit_transform=False)
            
            # Get predictions from trained models
            algorithm_results = {'combined_results': []}
            
            for i, resume_text in enumerate(resume_texts):
                combined_result = {
                    'resume_index': i,
                    'algorithm_scores': {},
                    'errors': []
                }
                
                scores = []
                
                for method in methods:
                    try:
                        model_path = os.path.join(models_dir, f'{method}_{position}_academic.joblib')
                        
                        if os.path.exists(model_path):
                            model = joblib.load(model_path)
                            prediction = model.predict([features[i]])[0]
                            score = float(np.clip(prediction, 0, 1))  # Ensure 0-1 range
                            
                            combined_result['algorithm_scores'][method] = {
                                'score': score,
                                'details': {
                                    'model_type': 'academic_trained',
                                    'features_used': features.shape[1],
                                    'prediction_raw': float(prediction)
                                }
                            }
                            scores.append(score)
                        else:
                            # Fallback to default algorithms
                            algorithm = algorithm_manager.get_algorithm(method)
                            if algorithm:
                                result = algorithm.process_single(resume_text, job_description, position)
                                combined_result['algorithm_scores'][method] = result
                                scores.append(result['score'])
                            
                    except Exception as e:
                        log.error(f"Error with academic model {method}: {e}")
                        combined_result['errors'].append(f"{method}: processing failed")
                
                # Calculate combined score
                if scores:
                    combined_result['combined_score'] = float(np.mean(scores))
                    combined_result['weighted_score'] = combined_result['combined_score']
                else:
                    combined_result['combined_score'] = 0.0
                    combined_result['weighted_score'] = 0.0
                
                algorithm_results['combined_results'].append(combined_result)
            
            # Rank results
            algorithm_results['combined_results'].sort(key=lambda x: x['combined_score'], reverse=True)
            for i, result in enumerate(algorithm_results['combined_results']):
                result['rank'] = i + 1
            
            return algorithm_results
            
        except Exception as e:
            log.error(f"Error in academic model processing: {e}")
            # Fallback to regular processing
            return algorithm_manager.process_resumes_parallel(resume_texts, job_description, methods, position)
    
    def _extract_skills_list(extracted_skills: dict) -> list:
        """Extract flat list of skills from NER results"""
        skills = []
        try:
            for category, skill_list in extracted_skills.items():
                for skill_data in skill_list:
                    if isinstance(skill_data, dict) and 'skill' in skill_data:
                        skills.append(skill_data['skill'].title())
                    elif isinstance(skill_data, str):
                        skills.append(skill_data.title())
            return list(set(skills))  # Remove duplicates
        except Exception as e:
            log.error(f"Error extracting skills: {e}")
            return []
    
    return app


# WSGI entrypoint for Gunicorn / Docker (`app:app`). FLASK_ENV selects config (see Dockerfile).
app = create_app(os.getenv('FLASK_ENV', 'development'))

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=app.config['DEBUG'])
